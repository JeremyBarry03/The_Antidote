import {ReplayApp} from './app.js';

const app = new ReplayApp();
try {await app.start();}
catch (error) {app.showError(error);}
