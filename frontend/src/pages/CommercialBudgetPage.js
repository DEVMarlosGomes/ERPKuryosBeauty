import { useCallback, useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FileText, Search, CheckCircle2, Clock, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import PropostaPedidoModal from "@/components/PropostaPedidoModal";

const STAGE_LABELS = {
  projeto_em_discussao: "Projeto em discussao",
  amostra_solicitada: "Amostra solicitada",
  amostra_em_desenvolvimento: "Amostra em desenvolvimento",
  amostra_enviada: "Amostra enviada",
  cotacao: "Cotacao",
  orcamento_completo: "Orcamento completo",
  em_negociacao: "Em negociacao",
  pedido_aprovado: "Pedido aprovado",
  projeto_arquivado: "Arquivado",
};

function statusConfig(project) {
  if (project.stage === "pedido_aprovado") return { label: "Pedido aprovado", cls: "bg-green-100 text-green-700", icon: CheckCircle2 };
  if (project.stage === "orcamento_completo") return { label: "Orcamento completo", cls: "bg-rose-100 text-rose-700", icon: FileText };
  if (project.stage === "cotacao") return { label: "Cotacao", cls: "bg-orange-100 text-orange-700", icon: FileText };
  if (project.stage === "em_negociacao") return { label: "Pronto para proposta", cls: "bg-amber-100 text-amber-700", icon: FileText };
  if (project.stage === "amostra_enviada") return { label: "Aguardando negociacao", cls: "bg-blue-100 text-blue-700", icon: Clock };
  return { label: STAGE_LABELS[project.stage] || "Em andamento", cls: "bg-slate-100 text-slate-700", icon: AlertTriangle };
}

function actionForProject(project) {
  if (project.stage === "cotacao") return { label: "Abrir cotacao", initialTab: "proposta" };
  if (project.stage === "orcamento_completo") return { label: "Abrir orcamento", initialTab: "pedido" };
  return { label: "Gerar orcamento", initialTab: project.stage === "amostra_enviada" ? "proposta" : "pedido" };
}

export default function CommercialBudgetPage() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [stage, setStage] = useState("all");
  const [selected, setSelected] = useState(null);
  const [selectedInitialTab, setSelectedInitialTab] = useState("proposta");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/crm/projects");
      setProjects(Array.isArray(data) ? data : []);
    } catch (err) {
      toast.error(formatApiError(err));
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return projects.filter((project) => {
      const normalizedStage = project.stage === "amostras" ? "amostra_solicitada" : project.stage;
      if (stage !== "all" && normalizedStage !== stage) return false;
      if (!q) return true;
      return `${project.nome_projeto || ""} ${project.cliente_nome || ""} ${project.categoria || ""}`.toLowerCase().includes(q);
    });
  }, [projects, search, stage]);

  const kpis = useMemo(() => ({
    total: projects.length,
    cotacoes: projects.filter((p) => p.stage === "cotacao").length,
    completos: projects.filter((p) => p.stage === "orcamento_completo").length,
    negociacao: projects.filter((p) => p.stage === "em_negociacao").length,
    enviados: projects.filter((p) => p.stage === "amostra_enviada").length,
    aprovados: projects.filter((p) => p.stage === "pedido_aprovado").length,
  }), [projects]);

  const openProject = (project) => {
    const action = actionForProject(project);
    setSelectedInitialTab(action.initialTab);
    setSelected(project);
  };

  return (
    <div className="min-h-screen space-y-5 p-4 md:p-6" data-testid="commercial-budget-page">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <FileText className="h-6 w-6 text-primary" />
            Orcamentos
          </h1>
          <p className="text-sm text-muted-foreground">
            Gere proposta comercial a partir das amostras aprovadas do projeto.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Kpi label="Projetos" value={kpis.total} />
        <Kpi label="Cotacao" value={kpis.cotacoes} />
        <Kpi label="Orc. completo" value={kpis.completos} />
        <Kpi label="Em negociacao" value={kpis.negociacao} />
        <Kpi label="Amostras enviadas" value={kpis.enviados} />
        <Kpi label="Pedidos aprovados" value={kpis.aprovados} />
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="grid gap-3 md:grid-cols-[1fr_220px]">
            <div className="relative">
              <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" placeholder="Buscar projeto, cliente ou categoria..." />
            </div>
            <Select value={stage} onValueChange={setStage}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Todos os estagios</SelectItem>
                <SelectItem value="amostra_enviada">Amostra enviada</SelectItem>
                <SelectItem value="cotacao">Cotacao</SelectItem>
                <SelectItem value="orcamento_completo">Orcamento completo</SelectItem>
                <SelectItem value="em_negociacao">Em negociacao</SelectItem>
                <SelectItem value="pedido_aprovado">Pedido aprovado</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-3">
        {loading ? (
          <Card><CardContent className="p-8 text-center text-muted-foreground">Carregando projetos...</CardContent></Card>
        ) : filtered.length === 0 ? (
          <Card><CardContent className="p-8 text-center text-muted-foreground">Nenhum projeto encontrado.</CardContent></Card>
        ) : filtered.map((project) => {
          const cfg = statusConfig(project);
          const Icon = cfg.icon;
          const action = actionForProject(project);
          return (
            <Card key={project.id} className="overflow-hidden">
              <CardContent className="grid gap-4 p-4 md:grid-cols-[1fr_auto] md:items-center">
                <div className="min-w-0">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge className={cfg.cls}><Icon className="mr-1 h-3 w-3" />{cfg.label}</Badge>
                    {project.categoria && <Badge variant="outline">{project.categoria}</Badge>}
                  </div>
                  <h2 className="truncate text-base font-semibold">{project.nome_projeto || "Projeto sem nome"}</h2>
                  <p className="truncate text-sm text-muted-foreground">{project.cliente_nome || "Cliente nao informado"}</p>
                </div>
                <Button onClick={() => openProject(project)} className="w-full gap-2 md:w-auto">
                  <FileText className="h-4 w-4" />
                  {action.label}
                </Button>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <PropostaPedidoModal
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) {
            setSelected(null);
            setSelectedInitialTab("proposta");
          }
        }}
        projeto={selected}
        initialTab={selectedInitialTab}
        onSaved={load}
      />
    </div>
  );
}

function Kpi({ label, value }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-2xl font-semibold">{Number(value || 0).toLocaleString("pt-BR")}</p>
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      </CardContent>
    </Card>
  );
}
