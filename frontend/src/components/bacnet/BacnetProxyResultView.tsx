import type { BacnetProxyResult } from "@/lib/crud-api";
import { BacnetProxyEnvelopeView } from "@/components/ui/pretty-api-response";

type Props = {
  label: string;
  data: BacnetProxyResult | null;
};

/**
 * Pretty view for Open-FDD /bacnet/* proxy responses: unwrap JSON-RPC, format BaseResponse / tables, collapsible raw JSON.
 */
export function BacnetProxyResultView({ label, data }: Props) {
  if (data == null) return null;
  return <BacnetProxyEnvelopeView label={label} data={data} />;
}
