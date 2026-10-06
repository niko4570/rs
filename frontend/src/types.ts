export type Source = {
  title: string | null;
  url: string;
  snippet_used: string | null;
};

export type BulletCitation = {
  bullet_index: number;
  source_url: string | null;
  excerpt: string;
};

export type SummaryResult = {
  summary_bullets: string[];
  key_details: string;
  sources: Source[];
  caveats: string[];
  citations: BulletCitation[];
};
