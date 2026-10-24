import {mountAntidoteAscii} from './assets/antidote-ascii/index.js';
import settings from './assets/antidote-ascii/settings.js';

// Separate entry point: no replay state, API requests or model dependencies.
const header=document.getElementById('antidote-header');
const artwork=header?.querySelector('#ah-ascii');
if(artwork){
  try{
    mountAntidoteAscii(artwork,{
      settings,
      figureElement:header.querySelector('.ah-art-frame'),
      maxWidth:760,
      fps:20,
      label:'Animated numerical branching sculpture for Antidote'
    });
  }catch(error){
    artwork.dataset.animationError='true';
    console.warn('Antidote header artwork could not start.',error);
  }
}
