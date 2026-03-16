/**
 * Shared OpenAI model options for Overview AI chat and Data Model Setup (Tag with OpenAI).
 * Two options: GPT-5 mini (default, cost-efficient) and GPT-5.4 pro (for more complex tasks).
 */

export const DEFAULT_AI_MODEL = "gpt-5-mini";

export const AI_MODEL_OPTIONS: { value: string; label: string }[] = [
  { value: "gpt-5-mini", label: "GPT-5 mini (default, cost-efficient)" },
  { value: "gpt-5.4-pro", label: "GPT-5.4 pro (for more complex tasks)" },
];
