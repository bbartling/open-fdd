import { Card, CardContent } from "@/components/ui/card";
import { BarChart2 } from "lucide-react";

export function DiagnosticsPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Diagnostics</h1>
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 px-6 text-center">
          <BarChart2 className="mb-4 h-12 w-12 text-muted-foreground" aria-hidden />
          <p className="text-lg font-medium text-foreground">Coming soon</p>
          <p className="mt-2 max-w-sm text-sm text-muted-foreground">
            Diagnostics and analytics will be available in a future version.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
