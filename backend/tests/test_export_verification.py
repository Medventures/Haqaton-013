from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from threading import Barrier

import pytest
from pypdf import PdfReader
from sqlalchemy import select, text

from app.config import Settings
from app.forms import get_template
from app.models import DocumentRow
from app.schemas import ConsultationData, TemplateFieldValue, VitalSigns
from test_forms import EXPECTED, document_text, export as docx_export
from test_pdf import export as pdf_export
from test_transcript_revisions import client, sqlite_client, prepared


@pytest.mark.parametrize('template_id', EXPECTED)
def test_sparse_exports_preserve_explicit_negatives_and_originals(template_id):
    from app.forms import _source_path
    original = _source_path(template_id).read_bytes()
    field = next(f for f in get_template(template_id)['fields'] if 'clinical_field' not in f)
    data = ConsultationData(allergies=['Отрицает'], objective_status='Хрипов нет',
        vital_signs=VitalSigns(heart_rate='0'), additional_notes='Не указано',
        template_fields=[TemplateFieldValue(key=field['key'], value='Нет')])
    before = data.model_dump()
    for output in (document_text(docx_export(template_id, data)),
                   '\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf_export(template_id, data))).pages)):
        for value in ('Отрицает', 'Хрипов нет', 'Нет', 'Не указано', '0'):
            assert value in output
        assert 'Предварительный диагноз:' not in output
        assert 'Жалобы:' not in output
    assert data.model_dump() == before
    assert _source_path(template_id).read_bytes() == original


def approved(client):
    headers, cid, prefix, _, doc = prepared(client, review=True)
    assert client.post(prefix+'/approve', headers=headers, json={'version':doc['version']}).status_code == 200
    return headers, cid, prefix


def qr_url(content):
    reader = PdfReader(BytesIO(content))
    urls = [a.get_object().get('/A', {}).get('/URI', '') for page in reader.pages for a in page.get('/Annots', [])]
    return next(url for url in urls if '/verify/' in url)


def test_pdf_is_immutable_and_public_verification_has_no_private_data(client, monkeypatch):
    headers, cid, prefix = approved(client)
    first = client.get(prefix+'/document.pdf', headers={**headers, 'Host':'attacker.example'})
    assert first.status_code == 200
    url = qr_url(first.content)
    assert url.startswith('http://localhost:5173/verify/')
    public_id = url.rsplit('/',1)[1]
    assert len(public_id) >= 32 and cid not in url
    public = client.get('/api/v1/verification/'+public_id)
    assert public.status_code == 200
    assert set(public.json()) == {'issuer','issued_at','status','sha256'}
    assert public.json()['issuer'] == 'MedHub'
    assert public.json()['status'] == 'valid'
    assert public.json()['sha256'] == sha256(first.content).hexdigest()
    assert public.headers['cache-control'] == 'no-store'
    assert client.get('/api/v1/verification/not-a-real-id').status_code == 404
    assert client.get(prefix+'/document.pdf').status_code == 401
    def unexpected(*args, **kwargs):
        raise AssertionError('Immutable artifact must not be rendered again')
    monkeypatch.setattr('app.forms.render_pdf', unexpected)
    assert client.get(prefix+'/document.pdf', headers=headers).content == first.content


def test_concurrent_first_pdf_requests_return_one_artifact(client):
    headers, cid, prefix = approved(client)
    barrier = Barrier(2)
    def download(_):
        barrier.wait(timeout=10)
        return client.get(prefix+'/document.pdf', headers=headers)
    with ThreadPoolExecutor(2) as pool:
        replies = list(pool.map(download, range(2)))
    assert [r.status_code for r in replies] == [200,200]
    assert replies[0].content == replies[1].content
    with client.app.state.session_factory() as session:
        assert session.scalar(text('SELECT count(*) FROM export_artifacts')) == 1


def test_legacy_approved_without_transcript_is_lazily_issued(client):
    from app.models import TranscriptRow, TranscriptRevisionRow
    from sqlalchemy import delete
    headers, cid, prefix = approved(client)
    with client.app.state.session_factory() as session:
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == cid))
        original = row.doctor_approved_data.copy()
        row.source_transcript_revision = None
        tid = session.scalar(select(TranscriptRow.id).where(TranscriptRow.consultation_id == cid))
        session.execute(delete(TranscriptRevisionRow).where(TranscriptRevisionRow.transcript_id == tid))
        session.execute(delete(TranscriptRow).where(TranscriptRow.id == tid))
        session.commit()
    response = client.get(prefix+'/document.pdf', headers=headers)
    assert response.status_code == 200
    assert '/verify/' in qr_url(response.content)
    with client.app.state.session_factory() as session:
        row = session.scalar(select(DocumentRow).where(DocumentRow.consultation_id == cid))
        assert row.doctor_approved_data == original
        assert row.source_transcript_revision is None


def test_configured_https_origin_is_encoded_in_qr_not_host(client, monkeypatch):
    import app.forms.pdf as pdf
    real_qr = pdf.QrCodeWidget
    seen = []
    def record(value):
        seen.append(value)
        return real_qr(value)
    monkeypatch.setattr(pdf, 'QrCodeWidget', record)
    client.app.state.settings.public_base_url = 'https://verify.example.test'
    headers, _, prefix = approved(client)
    response = client.get(prefix+'/document.pdf', headers={**headers,'Host':'host-injection.test'})
    assert response.status_code == 200
    url = qr_url(response.content)
    assert url.startswith('https://verify.example.test/verify/')
    assert seen == [url]
    assert 'host-injection' not in url


@pytest.mark.parametrize('url', ['https://example.org?token=x','https://user:pass@example.org','javascript:alert(1)','http://public.example','https://example.org/#x'])
def test_public_base_url_rejects_unsafe_origins(url):
    with pytest.raises(ValueError):
        Settings(public_base_url=url).validate()
