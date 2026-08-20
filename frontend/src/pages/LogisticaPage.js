import { useNavigate } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { CalendarClock, PackageCheck, Truck, Warehouse } from "lucide-react";

const AREAS = [
  { title: "Estoque", description: "Saldo, setores, Kardex, FIFO e posicao CQ.", path: "/estoque", icon: Warehouse },
  { title: "WMS / Movimentacao", description: "Entradas, saidas, transferencias e ajustes.", path: "/estoque/movimentacao", icon: PackageCheck },
  { title: "Recebimento", description: "Entrada operacional de materiais e conferencias.", path: "/recebimento", icon: PackageCheck },
  { title: "Expedicao", description: "Separacao, conferencia, despacho e entrega.", path: "/expedicao", icon: Truck },
  { title: "Agendamentos", description: "Entregas e coletas vinculadas ao fluxo logistico.", path: "/logistica/agendamentos", icon: CalendarClock },
];

export default function LogisticaPage() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen space-y-5 p-4 md:p-6" data-testid="logistica-page">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Truck className="h-6 w-6 text-primary" />
          Logistica
        </h1>
        <p className="text-sm text-muted-foreground">Estoque, WMS, expedicao e agendamentos em um unico modulo.</p>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {AREAS.map((area) => {
          const Icon = area.icon;
          return (
            <Card key={area.title} className="overflow-hidden">
              <CardContent className="flex h-full flex-col gap-4 p-5">
                <div className="flex items-start gap-3">
                  <div className="rounded-md bg-primary/10 p-2 text-primary">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div>
                    <h2 className="font-semibold">{area.title}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">{area.description}</p>
                  </div>
                </div>
                <Button className="mt-auto w-full" variant="outline" onClick={() => navigate(area.path)}>
                  Abrir
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
