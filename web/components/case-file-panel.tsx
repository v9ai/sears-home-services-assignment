import { ShieldAlert, User } from "lucide-react";
import { CaseFile } from "@/lib/types";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

export function CaseFilePanel({ caseFile }: { caseFile: CaseFile }) {
  return (
    <Card className="overflow-y-auto text-sm">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Case File</CardTitle>
        <Badge variant={caseFile.safety_flag ? "destructive" : "secondary"}>
          {caseFile.safety_flag ? "Safety hold" : "Active"}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {caseFile.safety_flag && (
          <Alert variant="destructive">
            <ShieldAlert className="size-4" />
            <AlertDescription className="font-semibold text-destructive">
              Safety escalation triggered — DIY steps paused.
            </AlertDescription>
          </Alert>
        )}

        <Field label="Appliance">
          {caseFile.appliance_type ? (
            <Badge variant="outline">{caseFile.appliance_type}</Badge>
          ) : (
            <span className="italic text-muted-foreground">not yet identified</span>
          )}
        </Field>

        <Separator />

        <Field label="Brand / Model">
          {caseFile.brand ?? "—"} / {caseFile.model ?? "—"}
        </Field>

        <Separator />

        <Field label="Symptoms">
          {caseFile.symptoms.length === 0 ? (
            <div className="italic text-muted-foreground">none recorded yet</div>
          ) : (
            <div className="flex flex-col gap-2">
              {caseFile.symptoms.map((symptom, index) => (
                <div key={index} className="rounded-lg border bg-muted/30 p-2.5">
                  <div>{symptom.description}</div>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    <Badge variant="outline" className="font-normal">
                      onset: {symptom.onset}
                    </Badge>
                    {symptom.error_code && (
                      <Badge variant="outline" className="font-normal">
                        error: {symptom.error_code}
                      </Badge>
                    )}
                    {symptom.sound && (
                      <Badge variant="outline" className="font-normal">
                        sound: {symptom.sound}
                      </Badge>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Field>

        <Separator />

        <Field label="Steps given">
          {caseFile.steps_given.length === 0 ? (
            <div className="italic text-muted-foreground">none yet</div>
          ) : (
            <ol className="list-inside list-decimal space-y-1">
              {caseFile.steps_given.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
          )}
        </Field>

        <Separator />

        <Field label="Customer">
          <span className="flex items-center gap-1.5">
            <User className="size-3.5 text-muted-foreground" />
            {caseFile.customer.name ?? "—"}
            {caseFile.customer.zip ? ` · ${caseFile.customer.zip}` : ""}
            {caseFile.customer.email ? ` · ${caseFile.customer.email}` : ""}
          </span>
        </Field>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-sm">{children}</div>
    </div>
  );
}
