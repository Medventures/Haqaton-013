import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from './utils'

const variants = cva('inline-flex items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45', {
  variants: {
    variant: {
      primary: 'bg-teal text-white shadow-[0_7px_18px_rgba(8,126,131,.16)] hover:bg-[#066c70]',
      secondary: 'border border-[#d6e2e2] bg-white text-ink hover:bg-[#f2f8f7]',
      ghost: 'text-[#526b75] hover:bg-[#edf4f3] hover:text-ink',
      danger: 'bg-[#fff0ed] text-[#a63b2b] hover:bg-[#ffe2db]',
    },
    size: { default: 'h-10 px-4', sm: 'h-9 px-3', icon: 'h-10 w-10' },
  }, defaultVariants: { variant: 'primary', size: 'default' },
})

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> { asChild?: boolean }
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : 'button'
  return <Comp ref={ref} className={cn(variants({ variant, size }), className)} {...props} />
})
Button.displayName = 'Button'
