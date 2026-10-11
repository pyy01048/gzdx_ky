/// <reference types="vite/client" />

declare module '*.jsx' {
  const content: any
  export default content
}

declare module '*.js' {
  const content: any
  export default content
}

interface Window {
  __APP_VERSION__: string
}
