import {setupAppearance} from '/tracking/appearance.mjs';

setupAppearance();
const contents=document.getElementById('paper-contents');
contents.open=window.matchMedia('(min-width: 900px)').matches;
