import type { SummaryResult } from "./types";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const STATUS_MESSAGES: Record<number, string> = {
  400: "Could not process this input. Check that the URL is valid and try again.",
  413: "The file is too large. The maximum size is 10 MB.",
  500: "Something went wrong while processing this request. Please try again.",
  502: "The research service could not produce a valid result. Please try again.",
  503: "The research service is not configured. Check the local API configuration.",
};

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const data: unknown = await response.json();
    if (
      typeof data === "object" &&
      data !== null &&
      "detail" in data &&
      typeof data.detail === "string" &&
      data.detail.trim()
    ) {
      return data.detail;
    }
  } catch {
    // Response body was not JSON; fall through to the status message.
  }
  return (
    STATUS_MESSAGES[response.status] ??
    "An unexpected error occurred. Please try again."
  );
}

async function postResearch(form: FormData): Promise<SummaryResult> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/research`, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new Error(
      "Could not reach the research service. Make sure the local API is running.",
    );
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as SummaryResult;
}

export async function researchTopic(query: string): Promise<SummaryResult> {
  const form = new FormData();
  form.append("input_type", "topic");
  form.append("query", query);
  return postResearch(form);
}

export async function researchUrl(url: string): Promise<SummaryResult> {
  const form = new FormData();
  form.append("input_type", "url");
  form.append("url", url);
  return postResearch(form);
}

export async function researchFile(file: File): Promise<SummaryResult> {
  const form = new FormData();
  form.append("input_type", "file");
  form.append("file", file);
  return postResearch(form);
}
