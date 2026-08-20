import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CalendarClock, Loader2, Search, Truck } from "lucide-react";

const STATUS_CLASS = {
  pendente: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  preparando: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  conferido: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
  expedido: "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  entregue: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  cancelado: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300",
};

function formatDate(value) {
  if (!value) return "Sem data";
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("pt-BR");
}

export default function LogisticaAgendamentosPage() {
  const navigate = useNavigate();
  const [ordens, setOrdens] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        setLoading(true);
        const { data } = await api.get("/expedicao/ordens");
        if (active) setOrdens(Array.isArray(data) ? data : []);
      } catch (error) {
        toast.error(formatApiError(error, "Nao foi possivel carregar agendamentos."));
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, []);

  const agendamentos = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return ordens
      .filter((ordem) => ordem.previsao_entrega || ordem.data_expedicao || ordem.data_entrega)
      .filter((ordem) => {
        if (!normalized) return true;
        return [ordem.numero_exp, ordem.cliente_nome, ordem.order_numero, ordem.transportadora]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(normalized));
      })
      .sort((a, b) => String(a.previsao_entrega || "").localeCompare(String(b.previsao_entrega || "")));
  }, [ordens, query]);

  return (
    <div className="min-h-screen space-y-5 p-4 md:p-6" data-testid="logistica-agendamentos-page">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <CalendarClock className="h-6 w-6 text-primary" />
            Agendamentos Logisticos
          </h1>
          <p className="text-sm text-muted-foreground">Entregas e coletas vinculadas a ordens de expedicao.</p>
        </div>
        <Button variant="outline" onClick={() => navigate("/expedicao")}>
          <Truck className="mr-2 h-4 w-4" />
          Abrir Expedicao
        </Button>
      </div>

      <div className="flex items-center gap-2 rounded-md border bg-card px-3 py-2">
        <Search className="h-4 w-4 text-muted-foreground" />
        <input
          className="min-w-0 flex-1 bg-transparent text-sm outline-none"
          placeholder="Buscar por EXP, cliente, pedido ou transportadora..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {loading ? (
        <div className="flex h-48 items-center justify-center text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Carregando agendamentos
        </div>
      ) : agendamentos.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            Nenhum agendamento logistico encontrado.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {agendamentos.map((ordem) => (
            <Card key={ordem.id} className="overflow-hidden">
              <CardContent className="grid gap-4 p-4 md:grid-cols-[160px_1fr_auto] md:items-center">
                <div>
                  <p className="text-xs font-medium uppercase text-muted-foreground">Previsao</p>
                  <p className="font-semibold">{formatDate(ordem.previsao_entrega)}</p>
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{ordem.numero_exp}</span>
                    <Badge className={STATUS_CLASS[ordem.status] || STATUS_CLASS.pendente}>
                      {ordem.status || "pendente"}
                    </Badge>
                  </div>
                  <p className="mt-1 truncate text-sm text-muted-foreground">
                    {ordem.cliente_nome || "Cliente nao informado"}
                    {ordem.order_numero ? ` - Pedido ${ordem.order_numero}` : ""}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {ordem.transportadora || "Transportadora nao definida"}
                  </p>
                </div>
                <Button variant="outline" onClick={() => navigate("/expedicao")}>
                  Ver ordem
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
