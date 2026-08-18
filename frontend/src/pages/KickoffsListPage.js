import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { formatApiError } from "@/lib/formatError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ClipboardList, Search, ArrowRight } from "lucide-react";
import { toast } from "sonner";

const STATUS_OPTIONS = [
  { value: "all", label: "Todos os status" },
  { value: "em_preenchimento", label: "Em preenchimento" },
  { value: "aguardando_aprovacao", label: "Aguardando aprovacao" },
  { value: "aprovado", label: "Aprovado" },
  { value: "em_revisao", label: "Em revisao" },
  { value: "substituida", label: "Substituida" },
];

const STATUS_TONE = {
  em_preenchimento: "secondary",
  aguardando_aprovacao: "default",
  aprovado: "outline",
  em_revisao: "secondary",
  substituida: "destructive",
};

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString("pt-BR");
}

export default function KickoffsListPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [kickoffs, setKickoffs] = useState([]);
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");

  const loadKickoffs = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (status !== "all") params.status = status;
      const { data } = await api.get("/kickoffs", { params });
      setKickoffs(Array.isArray(data) ? data : []);
    } catch (error) {
      toast.error(formatApiError(error));
      setKickoffs([]);
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    loadKickoffs();
  }, [loadKickoffs]);

  const filteredKickoffs = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return kickoffs;
    return kickoffs.filter((item) => {
      const blob = [
        item.numero_kickoff,
        item?.bloco1?.cliente,
        item?.bloco1?.projeto_vinculado,
        item.status,
        item.versao,
      ].join(" ").toLowerCase();
      return blob.includes(term);
    });
  }, [kickoffs, search]);

  const summary = useMemo(() => ({
    total: kickoffs.length,
    pendentes: kickoffs.filter((item) => item.status === "em_preenchimento").length,
    aprovacao: kickoffs.filter((item) => item.status === "aguardando_aprovacao").length,
    aprovados: kickoffs.filter((item) => item.status === "aprovado").length,
  }), [kickoffs]);

  return (
    <div className="p-4 sm:p-6 lg:p-8 space-y-6" data-testid="kickoffs-list-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl sm:text-3xl font-heading font-semibold tracking-tight">Kickoffs</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Contratos de industrializacao e liberacao operacional por projeto.
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Total</p><p className="text-2xl font-semibold mt-1">{summary.total}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Preenchimento</p><p className="text-2xl font-semibold mt-1">{summary.pendentes}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Aguardando aprovacao</p><p className="text-2xl font-semibold mt-1">{summary.aprovacao}</p></CardContent></Card>
        <Card><CardContent className="p-4"><p className="text-xs text-muted-foreground">Aprovados</p><p className="text-2xl font-semibold mt-1">{summary.aprovados}</p></CardContent></Card>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[280px] flex-1">
          <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar por numero, cliente ou projeto..."
            className="pl-9"
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-[220px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="outline" onClick={loadKickoffs}>Atualizar</Button>
      </div>

      <Card className="overflow-hidden">
        <CardContent className="p-0">
          {loading ? (
            <div className="p-8 text-sm text-muted-foreground">Carregando kickoffs...</div>
          ) : filteredKickoffs.length === 0 ? (
            <div className="p-8 text-sm text-muted-foreground">Nenhum kickoff encontrado.</div>
          ) : (
            <div className="divide-y divide-border">
              {filteredKickoffs.map((kickoff) => (
                <button
                  key={kickoff.id}
                  type="button"
                  onClick={() => navigate(`/kickoff/${kickoff.id}`)}
                  className="w-full p-4 text-left hover:bg-accent/40 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center">
                          <ClipboardList className="h-4 w-4" />
                        </div>
                        <div>
                          <p className="font-medium">{kickoff.numero_kickoff}</p>
                          <p className="text-sm text-muted-foreground">
                            {kickoff?.bloco1?.cliente || "-"} · {kickoff?.bloco1?.projeto_vinculado || "-"}
                          </p>
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge variant={STATUS_TONE[kickoff.status] || "secondary"}>{kickoff.status}</Badge>
                      <Badge variant="outline">{kickoff.versao}</Badge>
                      <ArrowRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-5 text-sm">
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Abertura</p>
                      <p>{formatDate(kickoff.data_abertura)}</p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Aprovacao</p>
                      <p>{formatDate(kickoff.data_aprovacao)}</p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Amostra</p>
                      <p>{kickoff?.bloco1?.amostra_aprovada || "-"}</p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Versao atual</p>
                      <p>{kickoff.versao}</p>
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Fila atual</p>
                      <p>{kickoff.responsavel_aprovacao_pendente || "-"}</p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
