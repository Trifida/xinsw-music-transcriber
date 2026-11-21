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
  await session.setProfile(false);
  const fontSize = Number(process.env.DOLCE_JIANPU_FONT_SIZE || 0);
  await session.applyRenderSettings({
    jpPaper: paper,
    ...(Number.isFinite(fontSize) && fontSize > 0 ? { fontSize } : {})
  });
  await session.setViewMode("original");

  const pages = session.pages();
  if (!pages.length) throw new Error("Dolce returned no numbered-notation pages.");
  const score = session.currentScoreDoc();
  const measureCount = score?.songs?.[0]?.parts?.[0]?.measures?.length ?? 0;
  const measures = score?.songs?.[0]?.parts?.[0]?.measures ?? [];
  const noteCount = measures.reduce(
    (sum, measure) => sum + measure.elements.filter((element) => element.kind === "chord").length, 0
  );
  const barlineCount = measures.reduce((sum, measure) => sum + (measure.barlines?.length ?? 0), 0);
  const layout = session.painter.original;
  const placedPageCount = layout?.placed?.pages?.length ?? 0;
  const placedGroupCount = layout?.placed?.pages?.reduce((sum, page) => sum + page.groups.length, 0) ?? 0;
  const activeStyle = session.style.styleOf("original");
  const pageSizes = pages.map((_, index) => session.painter.pageSize(index));

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
    paper,
    applied_paper: activeStyle.page.paper ?? null,
    font_size: session.style.fontSize,
    layout_page: session.style.layoutPage,
    page_sizes: pageSizes,
    measure_count: measureCount,
    note_count: noteCount,
    barline_count: barlineCount,
    placed_page_count: placedPageCount,
    placed_group_count: placedGroupCount,
    svg_files: files,
    status: session.status || "Dolce headless engraving completed"
  }));
}

main().catch((error) => {
  process.stderr.write(`Dolce render failed: ${error?.stack || error}\n`);
  process.exitCode = 1;
});
