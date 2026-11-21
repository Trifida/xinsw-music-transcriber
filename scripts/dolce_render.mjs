#!/usr/bin/env node
/**
 * Server-side Dolce renderer.
 *
 * Converts MusicXML with Dolce's own ScoreDoc -> jianpu-ly serializer, then
 * loads that JLY text through Dolce's JLY adapter. That adapter applies the
 * same four-measures-per-line reflow used by the editor before A4 pagination.
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
  const { HeadlessSession, meta, emitJly } = await import(pathToFileURL(entry).href);
  const bytes = new Uint8Array(await readFile(input));
  const session = new HeadlessSession(meta);

  // First import the source MusicXML and let Dolce map absolute pitches into scale degrees.
  session.load(bytes, path.basename(input));
  const sourceScore = session.currentScoreDoc();
  if (!sourceScore) throw new Error("Dolce could not parse the input MusicXML into a score.");

  // Reuse Dolce's own serializer. Its JLY format carries lyrics and writes four measures per line.
  const exported = emitJly(sourceScore);
  const jlyText = exported?.text;
  if (!jlyText || !jlyText.trim()) throw new Error("Dolce produced an empty jianpu-ly document.");

  await mkdir(outDir, { recursive: true });
  const jlyName = "jianpu-dolce.jly";
  await writeFile(path.join(outDir, jlyName), jlyText, "utf8");

  // Reload as JLY so the existing JLY adapter applies its native line reflow before engraving.
  session.load(new TextEncoder().encode(jlyText), jlyName);
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
  const measures = score?.songs?.[0]?.parts?.[0]?.measures ?? [];
  const measureCount = measures.length;
  const noteCount = measures.reduce(
    (sum, measure) => sum + measure.elements.filter((element) => element.kind === "chord").length, 0
  );
  const barlineCount = measures.reduce((sum, measure) => sum + (measure.barlines?.length ?? 0), 0);
  const layout = session.painter.original;
  const placedPageCount = layout?.placed?.pages?.length ?? 0;
  const placedGroupCount = layout?.placed?.pages?.reduce((sum, page) => sum + page.groups.length, 0) ?? 0;
  const lineStartCount = layout?.lineStarts?.length ?? 0;
  const actualNoteSize = layout?.metrics?.style?.size?.note ?? null;
  const svgLength = pages[0]?.length ?? 0;
  const activeStyle = session.style.styleOf("original");
  const pageSizes = pages.map((_, index) => session.painter.pageSize(index));

  const files = [];
  for (let i = 0; i < pages.length; i++) {
    let svg = pages[i];
    svg = svg.replace(/<svg\\b([^>]*)>/, (_whole, rawAttrs) => {
      let attrs = rawAttrs;
      const viewBox = /viewBox=["']\\s*0\\s+0\\s+([\\d.]+)\\s+([\\d.]+)\\s*["']/i.exec(attrs);
      if (!/\\bxmlns=/.test(attrs)) attrs += ' xmlns="http://www.w3.org/2000/svg"';
      if (viewBox && !/\\bwidth=/.test(attrs)) attrs += ` width="${viewBox[1]}"`;
      if (viewBox && !/\\bheight=/.test(attrs)) attrs += ` height="${viewBox[2]}"`;
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
    line_start_count: lineStartCount,
    actual_note_size: actualNoteSize,
    svg_length: svgLength,
    svg_files: files,
    jly_file: jlyName,
    warnings: Array.isArray(exported.warnings) ? exported.warnings : [],
    status: session.status || "Dolce headless engraving completed"
  }));
}

main().catch((error) => {
  process.stderr.write(`Dolce render failed: ${error?.stack || error}\\n`);
  process.exitCode = 1;
});
