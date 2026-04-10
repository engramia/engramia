import fs from "node:fs";
import path from "node:path";

export type LegalDoc = {
  slug: string;
  title: string;
  filename: string;
  content: string;
};

const LEGAL_DIR = path.join(process.cwd(), "src", "content", "legal");

/** Internal docs that should not appear on the public website. */
const EXCLUDED_FILES = new Set(["key-legal-design-decisions.md"]);

function slugFromFilename(filename: string) {
  return filename.toLowerCase().replace(/\.md$/, "").replace(/_/g, "-");
}

function titleFromContent(filename: string, content: string) {
  const firstHeading = content.match(/^#\s+(.+)$/m)?.[1]?.trim();
  return firstHeading || filename.replace(/\.md$/, "").replace(/_/g, " ");
}

export function getLegalDocs(): LegalDoc[] {
  return fs
    .readdirSync(LEGAL_DIR)
    .filter((name) => name.endsWith(".md") && !EXCLUDED_FILES.has(name))
    .sort()
    .map((filename) => {
      const content = fs.readFileSync(path.join(LEGAL_DIR, filename), "utf8");
      return {
        slug: slugFromFilename(filename),
        title: titleFromContent(filename, content),
        filename,
        content,
      };
    });
}

export function getLegalDoc(slug: string): LegalDoc | undefined {
  return getLegalDocs().find((doc) => doc.slug === slug);
}
