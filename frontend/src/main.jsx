import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import './styles/global.css'
import './styles/v2-design.css'
import './styles/kbmap.css'
import './styles/lanaccess.css'
import './styles/kbhealth.css'
import './styles/models.css'
import './styles/polish.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>
)
