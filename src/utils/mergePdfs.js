import { PDFDocument } from "pdf-lib";

/**
 * Merge multiple PDF files into one document (order preserved).
 * A single file returns a new copy with the same pages (valid unified output).
 * @param {File[]} pdfFiles
 * @returns {Promise<Uint8Array>}
 */
export async function mergePdfFiles(pdfFiles) {
  if (!pdfFiles.length) {
    throw new Error("No PDF files to merge");
  }

  const merged = await PDFDocument.create();

  for (const file of pdfFiles) {
    const raw = new Uint8Array(await file.arrayBuffer());
    const src = await PDFDocument.load(raw);
    const pageIndices = src.getPageIndices();
    const copiedPages = await merged.copyPages(src, pageIndices);
    copiedPages.forEach((page) => merged.addPage(page));
  }

  return merged.save();
}
