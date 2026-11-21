#!/usr/bin/env node
/**
 * Server-side Dolce renderer.
 *
 * Uses the exact same TypeScript engraving engine as the Dolce editor, through
 * its documented Node headless build. Input is MusicXML; output is one SVG per
 * numbered-notation page. Raster/PDF conversion is handled by the Python caller
 * with librsvg so the score remains vector in PDF.
 */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

async function main() {
  const input = process.argv[2];
  const outDir = process.argv[3];
  if (!input || !outDir) {
    throw new Error("Usage: node dolce_render.mjs <input.musicxml> <output_dir>");
  }

  const entry = process.env.DOLCE_CLI_ENTRY ||
    path.resolve(path.dirname(new URL(import.meta.url).pathname), "../vendor/dolce/out/cli/engrave.js");
  const { HeadlessSession, meta } = await import(pathToFileURL(entry).href);
  const bytes = new Uint8Array(await readFile(input));
  const session = new HeadlessSession(meta);

  session.load(bytes, path.basename(input));
  // Dolce defaults to a continuous long image; the product needs printable pages.
  const paper = process.env.DOLCE_JIANPU_PAPER || "A4";
  await session.applyRenderSettings({ jpPaper: paper });
  await session.setViewMode("original");

  const pages = session.pages();
  if (!pages.length) throw new Error("Dolce returned no numbered-notation pages.");

  await mkdir(outDir, { recursive: true });
  const files = [];
  for (let i = 0; i < pages.length; i++) {
    let svg = pages[i];
    svg = svg.replace(/<svg\b([^>]*)>/, (_whole, rawAttrs) => {
      let attrs = rawAttrs;
      const viewBox = /viewBox=["']\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*["']/i.exec(attrs);
      if (!/\bxmlns=/.test(attrs)) attrs += ' xmlns="http://www.w3.org/2000/svg"';
      if (viewBox && !/\bwidth=/.test(attrs)) attrs += ` width="${viewBox[1]}"`;
      if (viewBox && !/\bheight=/.test(attrs)) attrs += ` height="${viewBox[2]}"`;
      return `<svg${attrs}>`;
    });
    const name = `jianpu-dolce-${i + 1}.svg`;
    await writeFile(path.join(outDir, name), svg, "utf8");
    files.push(name);
  }

  process.stdout.write(JSON.stringify({
    ok: true,
    page_count: files.length,
    svg_files: files,
    status: session.status || "Dolce headless engraving completed"
  }));
}

main().catch((error) => {
  process.stderr.write(`Dolce render failed: ${error?.stack || error}\n`);
  process.exitCode = 1;
});
