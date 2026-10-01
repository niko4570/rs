export type Source = {
  title: string | null;
  url: string;
  snippet_used: string | null;
};

export type SummaryResult = {
  summary_bullets: string[];
  key_details: string;
  sources: Source[];
  caveats: string[];
};
