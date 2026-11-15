import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App';
import {startInstall} from './hooks/useInstall';
import 'highlight.js/styles/github-dark.css';
import 'katex/dist/katex.min.css';
import './style.css';

startInstall();
createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
