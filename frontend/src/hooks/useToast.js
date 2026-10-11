import { createContext, useContext } from 'react'

export const ToastContext = createContext({ push: () => {} })

/** const toast = useToast(); toast.push({ message, tone: 'error'|'success'|'info', action?: {label, onClick} }) */
export const useToast = () => useContext(ToastContext)
