// Render the application's local HTML through the available browser, offline.
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');
const {createHash} = require('node:crypto');
(async () => {
  const folder = path.resolve(process.argv[2]);
  console.log('Rendering current HTML in',folder);
  const browser = await chromium.launch({executablePath: process.env.V08_BROWSER, headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1050,height:1000},offline:true});
    const records=[];
    for (const name of fs.readdirSync(folder).filter(v=>v.endsWith('.html'))) {
      await page.goto(pathToFileURL(path.join(folder,name)).href);
      for (const format of ['A4','Letter']) {
        const target=path.join(folder,name.replace('.html','-'+format+'.pdf'));
        if(fs.existsSync(target))fs.unlinkSync(target);
        const buffer=await page.pdf({format,printBackground:false,displayHeaderFooter:false,preferCSSPageSize:false});
        fs.writeFileSync(target,buffer);
        console.log(path.basename(target),buffer.length,'bytes');
        records.push({html:name,format,pdf:path.basename(target),html_sha256:createHash('sha256').update(fs.readFileSync(path.join(folder,name))).digest('hex'),pdf_sha256:createHash('sha256').update(buffer).digest('hex')});
      }
    }
    fs.writeFileSync(path.join(folder,'browser-print.json'),JSON.stringify({status:'PASS',browser:await browser.version(),offline:true,records},null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
