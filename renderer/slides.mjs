import fs from 'node:fs/promises';
import pptxgen from 'pptxgenjs';

// Data enters through stdin. It is never evaluated as JavaScript or shell text.
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const plan = JSON.parse(Buffer.concat(chunks).toString('utf8'));
const output = process.argv[2];
if (!output || !Array.isArray(plan.slides) || plan.slides.length === 0) {
  throw new Error('A nonempty slide plan and output path are required');
}
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'brofessor';
pptx.subject = 'Source-grounded, editable presentation';
pptx.title = plan.title || 'brofessor';
pptx.company = 'brofessor';
pptx.lang = plan.language === 'ru' ? 'ru-RU' : 'en-US';
pptx.theme = { headFontFace: 'Arial', bodyFontFace: 'Arial', lang: pptx.lang };

const color = { ink: '142B39', muted: '526772', accent: '008773', paper: 'F8FAFA' };
for (const [index, item] of plan.slides.entries()) {
  const slide = pptx.addSlide();
  slide.background = { color: color.paper };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0, y: 0, w: 0.17, h: 7.5, line: { color: color.accent },
    fill: { color: color.accent },
  });
  slide.addText(String(item.title || ''), {
    x: 0.6, y: 0.48, w: 12.0, h: 1.0, fontSize: 29, bold: true,
    color: color.ink, margin: 0, breakLine: false, fit: 'shrink', valign: 'mid',
  });
  const bullets = item.bullets || [];
  if (bullets.length) {
    slide.addText(bullets.map(text => ({
      text: String(text),
      options: { bullet: { indent: 21 }, hanging: 5, breakLine: true },
    })), {
      x: 0.7, y: 1.72, w: 11.9, h: item.table ? 1.7 : 4.42,
      fontSize: 23, color: color.ink, paraSpaceAfterPt: 18,
      margin: 0.05, valign: 'top', fit: 'shrink',
    });
  }
  if (item.table) {
    const rows = [item.table.headers.map(text => ({ text, options: { bold: true, fill: 'E5F0EE' } })), ...item.table.rows];
    slide.addTable(rows, {
      x: 0.7, y: bullets.length ? 3.6 : 1.85, w: 11.9, h: bullets.length ? 2.45 : 4.2,
      border: { type: 'solid', color: 'C9D6D8', pt: 1 },
      fontSize: 18, color: color.ink, fill: 'FFFFFF', margin: 0.12,
      rowH: 0.55, bold: false, autoPage: false,
    });
  }
  const citations = (item.citations || []).map(String);
  slide.addText(citations.length ? citations.join('  ·  ') : 'brofessor', {
    x: 0.7, y: 6.7, w: 11.1, h: 0.4, fontSize: 10,
    color: color.muted, margin: 0, fit: 'shrink',
  });
  slide.addText(String(index + 1).padStart(2, '0'), {
    x: 12.0, y: 6.7, w: 0.6, h: 0.4, fontSize: 12,
    color: color.accent, align: 'right', margin: 0,
  });
  slide.addNotes([String(item.notes || ''), citations.length ? `Sources: ${citations.join('; ')}` : ''].filter(Boolean).join('\n\n'));
}
await pptx.writeFile({ fileName: output });
await fs.access(output);
