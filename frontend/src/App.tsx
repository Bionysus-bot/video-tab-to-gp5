 import Workspace from './pages/Workspace'
 import Studio from './pages/Studio'
 import './App.css'

 export default function App() {
   return new URLSearchParams(location.search).has('legacy') ? <Workspace /> : <Studio />
 }
