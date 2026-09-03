import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AlertTriangle, ArrowRight, CalendarClock, ClipboardCheck, Loader2, PackageCheck, RefreshCw, ShieldCheck, Truck, Warehouse } from "lucide-react";

const AREAS = [
  { title: "Recebimento", description: "Entrada de NF, conferencia e vinculo com PO.", path: "/recebimento", icon: PackageCheck },
  { title: "Quarentena CQ", description: "Material recebido fica bloqueado ate liberacao de qualidade.", path: "/recebimento", icon: ShieldCheck },
  { title: "Estoque / WMS", description: "Saldo, lote, endereco, FIFO, Kardex e posicao CQ.", path: "/estoque", icon: Warehouse },
  { title: "Movimentacao", description: "Entradas, saidas, transferencias, ajustes e historico.", path: "/estoque/movimentacao", icon: ClipboardCheck },
  { title: "Expedicao", description: "Separacao, conferencia, despacho, entrega e romaneio.", path: "/expedicao", icon: Truck },
  { title: "Agendamentos", description: "Entregas e coletas vinculadas ao fluxo logistico.", path: "/logistica/agendamentos", icon: CalendarClock },
];

export default function LogisticaPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [recebimentos, setRecebimentos] = useState([]);
  const [expedicoes, setExpedicoes] = useState([]);
  const [expDash, setExpDash] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [recRes, expRes, expDashRes] = await Promise.all([
        api.get("/recebimento/entradas").catch(() => ({ data: [] })),
        api.get("/expedicao/ordens").catch(() => ({ data: [] })),
        api.get("/expedicao/dashboard").catch(() => ({ data: null })),
      ]);
      setRecebimentos(Array.isArray(recRes.data) ? recRes.data : []);
      setExpedicoes(Array.isArray(expRes.data) ? expRes.data : []);
      setExpDash(expDashRes.data || null);
    } catch (error) {
      toast.error(formatApiError(error, "Nao foi possivel carregar Logistica."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const metrics = useMemo(() => {
    const recQuarentena = recebimentos.filter((r) => (r.status || "quarentena") === "quarentena").length;
    const recLiberados = recebimentos.filter((r) => r.status === "liberado").length;
    const expAbertas = expedicoes.filter((e) => !["entregue", "cancelado"].includes(e.status)).length;
    const agendadas = expedicoes.filter((e) => e.previsao_entrega || e.data_expedicao || e.data_entrega).length;
    return { recQuarentena, recLiberados, expAbertas, agendadas };
  }, [recebimentos, expedicoes]);

  return (
    <div className="min-h-screen space-y-5 p-4 md:p-6" data-testid="logistica-page">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <Truck className="h-6 w-6 text-primary" />
            Logistica
          </h1>
          <p className="text-sm text-muted-foreground">Recebimento, quarentena, WMS, expedicao e agendamentos no mesmo fluxo operacional.</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
          Atualizar
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card><CardContent className="p-4"><p className="text-xs uppercase text-muted-foreground">Recebimentos em CQ</p><p className="mt-1 text-2xl font-semibold text-amber-600">{metrics.recQuarentena}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs uppercase text-muted-foreground">Recebimentos liberados</p><p className="mt-1 text-2xl font-semibold text-emerald-600">{metrics.recLiberados}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs uppercase text-muted-foreground">Expedicoes abertas</p><p className="mt-1 text-2xl font-semibold">{expDash?.abertas ?? metrics.expAbertas}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs uppercase text-muted-foreground">Agendamentos</p><p className="mt-1 text-2xl font-semibold">{metrics.agendadas}</p></CardContent></Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Esteira logistica</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] md:items-center">
            {[
              ["Receber", "NF e PO conferidas", PackageCheck],
              ["Quarentena", "CQ bloqueia disponibilidade", ShieldCheck],
              ["Enderecar", "WMS, lote e etiqueta", Warehouse],
              ["Expedir", "Conferencia e romaneio", Truck],
            ].map(([title, desc, Icon], index) => (
              <div key={title} className="contents">
                <button
                  type="button"
                  onClick={() => navigate(index === 0 || index === 1 ? "/recebimento" : index === 2 ? "/estoque" : "/expedicao")}
                  className="rounded-lg border bg-card p-4 text-left transition hover:border-primary/40 hover:bg-muted/40"
                >
                  <Icon className="mb-3 h-5 w-5 text-primary" />
                  <p className="font-semibold">{title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{desc}</p>
                </button>
                {index < 3 && <ArrowRight className="hidden h-4 w-4 text-muted-foreground md:block" />}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="areas" className="w-full">
        <TabsList className="grid h-auto grid-cols-2 gap-1 md:grid-cols-4">
          <TabsTrigger value="areas">Areas</TabsTrigger>
          <TabsTrigger value="recebimentos">Recebimentos</TabsTrigger>
          <TabsTrigger value="expedicoes">Expedicoes</TabsTrigger>
          <TabsTrigger value="alertas">Alertas</TabsTrigger>
        </TabsList>

        <TabsContent value="areas" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
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
        </TabsContent>

        <TabsContent value="recebimentos" className="grid gap-3">
          {loading ? (
            <Card><CardContent className="py-10 text-center text-muted-foreground"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></CardContent></Card>
          ) : recebimentos.slice(0, 8).map((rec) => (
            <Card key={rec.id}>
              <CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono font-semibold">NF {rec.numero_nf}</span>
                    <Badge className={(rec.status || "quarentena") === "quarentena" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"}>
                      {rec.status || "quarentena"}
                    </Badge>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{rec.fornecedor_nome || "Fornecedor nao informado"} - {rec.items?.length || 0} item(ns)</p>
                </div>
                <Button variant="outline" onClick={() => navigate("/recebimento")}>Abrir recebimento</Button>
              </CardContent>
            </Card>
          ))}
          {!loading && recebimentos.length === 0 && <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">Nenhum recebimento registrado.</CardContent></Card>}
        </TabsContent>

        <TabsContent value="expedicoes" className="grid gap-3">
          {loading ? (
            <Card><CardContent className="py-10 text-center text-muted-foreground"><Loader2 className="mx-auto h-5 w-5 animate-spin" /></CardContent></Card>
          ) : expedicoes.slice(0, 8).map((exp) => (
            <Card key={exp.id}>
              <CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono font-semibold">{exp.numero_exp || exp.id}</span>
                    <Badge variant="outline">{exp.status || "pendente"}</Badge>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{exp.cliente_nome || "Cliente nao informado"}{exp.previsao_entrega ? ` - previsao ${exp.previsao_entrega}` : ""}</p>
                </div>
                <Button variant="outline" onClick={() => navigate("/expedicao")}>Abrir expedicao</Button>
              </CardContent>
            </Card>
          ))}
          {!loading && expedicoes.length === 0 && <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">Nenhuma expedicao registrada.</CardContent></Card>}
        </TabsContent>

        <TabsContent value="alertas" className="grid gap-3 md:grid-cols-2">
          <Card className={metrics.recQuarentena ? "border-amber-500/40" : ""}>
            <CardContent className="flex gap-3 p-4">
              <AlertTriangle className="mt-0.5 h-5 w-5 text-amber-500" />
              <div>
                <p className="font-semibold">Quarentena pendente</p>
                <p className="mt-1 text-sm text-muted-foreground">{metrics.recQuarentena} recebimento(s) aguardando decisao CQ antes de liberar estoque.</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="flex gap-3 p-4">
              <CalendarClock className="mt-0.5 h-5 w-5 text-primary" />
              <div>
                <p className="font-semibold">Agenda logistica</p>
                <p className="mt-1 text-sm text-muted-foreground">{metrics.agendadas} ordem(ns) com previsao, coleta ou entrega registrada.</p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
