import { createRoot } from 'react-dom/client';
import { AppProvider } from './state';
import { WorkspaceProvider } from './workspace';
import { App } from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(<AppProvider><WorkspaceProvider><App /></WorkspaceProvider></AppProvider>);
