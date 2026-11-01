import assert from 'node:assert/strict';
import {deflateSync} from 'node:zlib';
function png(width, height) {
  const crcTable = Array.from({length:256}, (_, n) => {let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0;});
  const crc = bytes => {let c = 0xffffffff; for (const b of bytes) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0;};
  const chunk = (type, data) => {const head = Buffer.alloc(4); head.writeUInt32BE(data.length); const body = Buffer.concat([Buffer.from(type), data]); const tail = Buffer.alloc(4); tail.writeUInt32BE(crc(body)); return Buffer.concat([head, body, tail]);};
  const header = Buffer.alloc(13); header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header.set([8, 2, 0, 0, 0], 8);
  const rows = Buffer.concat(Array.from({length:height}, (_, y) => Buffer.from([0, ...Array.from({length:width * 3}, (_, i) => (i * 7 + y * 13) % 256)])));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', header), chunk('IDAT', deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]);
}
/** A minimal PDF: one page per list of text lines; an empty list makes a page without text. */
function pdf(pages) {
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']; const kids = [];
  for (const lines of pages) {
    const stream = 'BT /F1 12 Tf 72 740 Td 18 TL ' + lines.map(line => `(${line}) Tj T*`).join(' ') + ' ET';
    objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${objects.length} 0 R >>`);
    kids.push(objects.length);
  }
  objects[1] = `<< /Type /Pages /Kids [${kids.map(kid => `${kid} 0 R`).join(' ')}] /Count ${kids.length} >>`;
  let out = '%PDF-1.4\n'; const offsets = [];
  objects.forEach((body, index) => {offsets.push(out.length); out += `${index + 1} 0 obj\n${body}\nendobj\n`;});
  const table = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n` + offsets.map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  return Buffer.from(out + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${table}\n%%EOF\n`, 'latin1');
}
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const url = process.env.TEST_BASE_URL;
if (!url) throw new Error('Run through tests/integration/run.py with OBSERVATOIRE_BROWSER=1.');
const browser = await chromium.launch({headless: true, ...(process.env.BROWSER_EXECUTABLE ? {executablePath:process.env.BROWSER_EXECUTABLE} : {}), args: ['--no-sandbox']});
try {
  const context = await browser.newContext({viewport:{width:1440,height:1000}});
  const page = await context.newPage(); const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
  const password='Integration-test-password-2026!';
  await page.addInitScript(() => {
    if (!localStorage.getItem('observatoir-chat-v1')) localStorage.setItem('observatoir-chat-v1',JSON.stringify({chats:[{id:'legacy',title:'Ancien historique local',messages:[{role:'user',content:'Ancien historique local'},{role:'assistant',content:'Une formule : $E=mc^2$.\n\n```python\nprint("Bonjour")\n```'}]}]}));
  });
  await page.goto(url);
  await page.locator('#login-form').waitFor({state:'visible'}); assert.equal(await page.locator('#chat-app').isHidden(),true);
  await page.locator('#login-username').fill('alice');await page.locator('#login-password').fill('wrong-password');await page.locator('#login-submit').click();
  await page.waitForFunction(()=>document.querySelector('#login-error').textContent.includes('incorrect'));
  await page.locator('#login-password').fill(password);await page.locator('#login-submit').click();
  await page.locator('#chat-app').waitFor({state:'visible'});await page.locator('#new-chat').click();
  await page.locator('#prompt').fill('Question privée Alice');await page.locator('#generation-toggle').click();
  await page.locator('#effort').selectOption('medium');await page.locator('#temperature').fill('0.3');await page.locator('#generation-close').click();
  await page.locator('#send').click();await page.waitForFunction(()=>document.querySelector('#stop').hidden&&document.querySelector('.assistant .message-content')?.textContent.includes('Bonjour'));
  assert.equal(await page.locator('#error').isHidden(),true);
  assert.match(await page.locator('.assistant .message-content').innerText(),/"temperature": 0.3/);
  await page.evaluate(()=>{globalThis.copied='';Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{globalThis.copied=text}},configurable:true})});
  await page.getByRole('button',{name:'Copier la question',exact:true}).click();assert.equal(await page.evaluate(()=>globalThis.copied),'Question privée Alice');
  assert.equal(await page.evaluate(()=>document.cookie.includes('observatoire_session')),false);
  const keys = await page.evaluate(()=>Object.keys(localStorage));assert.equal(keys.some(key=>key.includes('session')||key.includes('csrf')),false);
  // Two conversations write at once: the first keeps streaming while another one is used.
  await page.locator('#new-chat').click();await page.locator('#prompt').fill('slow');await page.locator('#send').click();
  await page.locator('.history-activity').waitFor({state:'visible'});
  await page.locator('#new-chat').click();await page.locator('#prompt').fill('Question parallèle');await page.locator('#send').click();
  await page.waitForFunction(()=>document.querySelector('#stop').hidden&&document.querySelector('.assistant .message-content')?.textContent.includes('Question parallèle'));
  assert.equal(await page.locator('.history-activity').count(),1);
  await page.getByRole('button',{name:'Renommer Sujet Question parallèle'}).click();
  await page.locator('.history-rename').fill('Titre choisi');await page.locator('.history-rename').press('Enter');
  await page.getByRole('button',{name:'Titre choisi',exact:true}).waitFor({state:'visible'});
  await page.locator('.history-row:has(.history-activity) .history-item').click();
  assert.equal(await page.locator('.user .message-content').innerText(),'slow');
  await page.waitForFunction(()=>!document.querySelector('.history-activity')&&document.querySelector('#stop').hidden&&document.querySelector('.assistant .message-content')?.textContent.includes('Réponse lente'));
  // An answer cut by the length limit can still be continued after a reload.
  await page.locator('#new-chat').click();await page.locator('#prompt').fill('longue réponse');await page.locator('#send').click();
  await page.getByRole('button',{name:'Continuer la réponse'}).waitFor({state:'visible'});
  await page.reload();await page.locator('#chat-app').waitFor({state:'visible'});await page.getByRole('button',{name:'Sujet longue réponse',exact:true}).first().click();
  await page.getByRole('button',{name:'Continuer la réponse'}).click();
  await page.waitForFunction(()=>document.querySelector('#stop').hidden&&document.querySelector('.assistant .message-content')?.textContent.includes('(suite)'));
  assert.equal(await page.getByRole('button',{name:'Continuer la réponse'}).count(),0);
  // The brand leads home: a new, empty chat.
  await page.locator('#library-link').click();await page.locator('#library').waitFor({state:'visible'});
  await page.locator('#brand').click();await page.locator('#welcome').waitFor({state:'visible'});
  assert.equal(await page.locator('#library').count(),0);assert.equal(await page.locator('.message').count(),0);
  // News: unread dot until opened, entries in plain words, highlighted alone in the sidebar.
  await page.locator('#news-unread').waitFor({state:'visible'});
  await page.locator('#news-link').click();await page.locator('#news .news-item').first().waitFor({state:'visible'});
  assert.equal(await page.locator('#news-unread').count(),0);
  assert.equal(await page.locator('.sidebar .active').count(),1);
  await page.reload();await page.locator('#chat-app').waitFor({state:'visible'});assert.equal(await page.locator('#news-unread').count(),0);
  await page.locator('#news-link').click();await page.locator('#brand').click();await page.locator('#welcome').waitFor({state:'visible'});
  assert.equal(await page.locator('#news').count(),0);
  // Images: sent with a question, shown in the message, received by Qwen, kept in the library.
  await page.locator('#new-chat').click();
  await page.locator('#attach-files').setInputFiles({name:'schema.png', mimeType:'image/png', buffer:png(48, 32)});
  await page.locator('.pending-image.is-ready').waitFor({state:'visible'});
  await page.locator('#prompt').fill('Que montre ce schéma ?');await page.locator('#send').click();
  await page.waitForFunction(()=>document.querySelector('#stop').hidden&&document.querySelector('.assistant .message-content')?.textContent.includes('data:image/png;base64'));
  assert.equal(await page.locator('.pending-image').count(),0);
  await page.locator('.message-image img').waitFor({state:'visible'});
  await page.locator('.message-image-open').click();await page.locator('.image-viewer img').waitFor({state:'visible'});await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Poser une question sur schema.png'}).click();await page.locator('.pending-image.is-ready').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.activeElement?.id==='prompt');await page.locator('.pending-remove').click();
  await page.locator('#library-link').click();await page.locator('.library-item').first().waitFor({state:'visible'});
  assert.equal(await page.locator('.library-name',{hasText:'schema.png'}).count(),1);
  assert.notEqual(await page.locator('.library-actions a.icon-button svg').first().evaluate(svg=>getComputedStyle(svg).stroke),'none');
  await page.getByRole('button',{name:'Nouvelle conversation avec schema.png'}).click();
  await page.locator('.pending-image.is-ready').waitFor({state:'visible'});assert.equal(await page.locator('.message').count(),0);
  await page.locator('.pending-remove').click();await page.locator('#library-link').click();await page.locator('.library-item').first().waitFor({state:'visible'});
  await page.locator('#new-chat').click();await page.locator('#attach-toggle').click();await page.getByRole('menuitem',{name:'Depuis la bibliothèque'}).click();
  await page.getByRole('button',{name:'Choisir schema.png'}).click();await page.getByRole('button',{name:'Ajouter (1)'}).click();
  await page.locator('.pending-image.is-ready').waitFor({state:'visible'});await page.locator('.pending-remove').click();
  await page.locator('#library-link').click();page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Supprimer schema.png'}).click();await page.locator('.library-name',{hasText:'schema.png'}).waitFor({state:'detached'});
  await page.getByRole('button',{name:'Sujet Que montre ce schéma ?',exact:true}).click();
  await page.locator('.message-image.is-missing').waitFor({state:'visible'});
  // Documents: read by the server (a PDF page by page), attached to a question, their text viewable.
  await page.locator('#new-chat').click();
  await page.locator('#attach-files').setInputFiles([{name:'rapport.pdf', mimeType:'application/pdf', buffer:pdf([['Rapport annuel','Premiere ligne du texte.','Seconde ligne du texte.'],[]])},
    {name:'notes.txt', mimeType:'text/plain', buffer:Buffer.from('Liste de courses : pain, café.')}]);
  await page.waitForFunction(()=>document.querySelectorAll('.pending-document.is-ready').length===2,null,{timeout:60000});
  assert.deepEqual(await page.locator('.pending-document-state').allTextContents(),['2 pages','Texte']);
  await page.locator('#prompt').fill('Résume ces documents');await page.locator('#send').click();
  await page.waitForFunction(()=>document.querySelector('#stop').hidden&&document.querySelector('.assistant .message-content')?.textContent.includes('Rapport annuel'));
  assert.equal(await page.locator('.message-document').count(),2);
  await page.getByRole('button',{name:'Voir le texte lu dans rapport.pdf'}).click();
  await page.locator('.document-viewer-text',{hasText:'treize[?]'}).waitFor({state:'visible'});await page.keyboard.press('Escape');
  await page.locator('#library-link').click();
  await page.locator('.library-state',{hasText:'2 pages · 1 lue sur l’image · 1 passage incertain'}).waitFor({state:'visible'});
  await page.locator('#new-chat').click();
  await page.reload();await page.locator('#chat-app').waitFor({state:'visible'});await page.getByRole('button',{name:'Sujet Question privée Alice',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.user .message-content')?.textContent==='Question privée Alice');
  await page.locator('#account-toggle').click();assert.equal(await page.locator('#import-legacy').isVisible(),true);
  page.once('dialog',dialog=>dialog.accept());await page.locator('#import-legacy').click();
  await page.getByRole('button',{name:'Ancien historique local',exact:true}).waitFor({state:'visible'});
  await page.getByRole('button',{name:'Ancien historique local',exact:true}).click();await page.locator('.katex').waitFor({state:'visible'});assert.equal(await page.locator('.line-numbers span').count(),1);
  await page.locator('#account-toggle').click();await page.locator('#logout').click();await page.locator('#login-form').waitFor({state:'visible'});
  assert.equal(await page.locator('.message').count(),0);
  await page.locator('#login-username').fill('bob');await page.locator('#login-password').fill('New-integration-password-2026!');await page.locator('#login-submit').click();
  await page.locator('#chat-app').waitFor({state:'visible'});assert.equal(await page.getByRole('button',{name:'Sujet Question privée Alice',exact:true}).count(),0);
  await page.locator('#prompt').fill('Question privée Bob');await page.locator('#send').click();await page.waitForFunction(()=>document.querySelector('#stop').hidden&&document.querySelector('.assistant .message-content')?.textContent.includes('Bonjour'));
  await page.locator('#account-toggle').click();await page.locator('#logout').click();await page.locator('#login-form').waitFor({state:'visible'});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.locator('#login-username').fill('alice');await page.locator('#login-password').fill(password);await page.locator('#login-submit').click();
  await page.locator('#chat-app').waitFor({state:'visible'});assert.equal(await page.getByRole('button',{name:'Sujet Question privée Bob',exact:true}).count(),0);
  await page.locator('#menu').click();await page.locator('#account-toggle').click();await page.locator('#change-password').click();
  await page.locator('#current-password').fill(password);await page.locator('#new-password').fill('Browser-new-password-2026!');await page.locator('#confirm-password').fill('Browser-new-password-2026!');await page.locator('#password-submit').click();
  await page.locator('#login-form').waitFor({state:'visible'});assert.match(await page.locator('#login-error').innerText(),/modifié/);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);
  console.log('Browser OK: login, history in PostgreSQL, settings, copy, parallel conversations, titles and rename, continue after reload, images and library, documents, opt-in import, account isolation, logout, password change, mobile.');
} finally {await browser.close();}
