import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { Factory, Search, Loader2, ArrowRight, Building2 } from "lucide-react";

const STATUS_CONFIG = {
  aberta:      { label: "Aberta",      color: "bg-blue-500/10 text-blue-600 border-blue-300 dark:text-blue-300" },
  em_processo: { label: "Em Processo", color: "bg-amber-500/10 text-amber-700 border-amber-300 dark:text-amber-300" },
  pausada:     { label: "Pausada",     color: "bg-orange-500/10 text-orange-600 border-orange-300 dark:text-orange-300" },
  concluida:   { label: "Concluída",   color: "bg-green-500/10 text-green-700 border-green-300 dark:text-green-300" },
  aguardando_confirmacao_pcp: { label: "Aguardando PCP", color: "bg-indigo-500/10 text-indigo-700 border-indigo-300 dark:text-indigo-300" },
  cancelada:   { label: "Cancelada",   color: "bg-red-500/10 text-red-700 border-red-300 dark:text-red-300" },
};

function formatDateBR(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("pt-BR"); } catch { return iso; }
}

export default function OPPage() {
  const navigate = useNavigate();
  const [ops, setOps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const fetchOps = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (statusFilter !== "all") params.status = statusFilter;
      if (search.trim()) params.q = search.trim();
      const res = await api.get("/ops", { params });
      setOps(res.data || []);
    } catch (err) {
      toast.error("Erro ao carregar OPs");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, search]);

  useEffect(() => { fetchOps(); }, [fetchOps]);

  const counts = {
    aberta: ops.filter(o => o.status === "aberta").length,
    em_processo: ops.filter(o => o.status === "em_processo").length,
    aguardando_confirmacao_pcp: ops.filter(o => o.status === "aguardando_confirmacao_pcp").length,
    concluida: ops.filter(o => o.status === "concluida").length,
  };

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-7xl mx-auto p-6 space-y-5">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-heading font-semibold tracking-tight flex items-center gap-2">
              <Factory className="h-6 w-6" />
              Ordens de Produção (OP)
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              OPs geradas a partir de Pedidos de Industrialização confirmados
            </p>
          </div>
        </div>

        {/* Mini stats */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { key: "aberta", label: "Abertas", color: "text-blue-600" },
            { key: "em_processo", label: "Em Processo", color: "text-amber-600" },
            { key: "aguardando_confirmacao_pcp", label: "Aguard. PCP", color: "text-indigo-600" },
            { key: "concluida", label: "Concluídas", color: "text-green-600" },
          ].map(({ key, label, color }) => (
            <div key={key} className="rounded-xl border bg-card p-4 text-center cursor-pointer hover:bg-accent/50" onClick={() => setStatusFilter(key)}>
              <p className={`text-2xl font-bold mono-num ${color}`}>{counts[key]}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 flex-wrap">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-44"><SelectValue placeholder="Status" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Todos os status</SelectItem>
              {Object.entries(STATUS_CONFIG).map(([v, c]) => (
                <SelectItem key={v} value={v}>{c.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Buscar OP, cliente ou projeto..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>

        {/* List */}
        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : ops.length === 0 ? (
          <div className="text-center py-20">
            <Factory className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <p className="text-muted-foreground font-medium">Nenhuma OP encontrada.</p>
            <p className="text-sm text-muted-foreground mt-1">OPs são criadas ao confirmar um Pedido de Industrialização.</p>
          </div>
        ) : (
          <div className="border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/30">
                  <th className="text-left p-3 font-semibold text-xs uppercase tracking-wide">OP</th>
                  <th className="text-left p-3 font-semibold text-xs uppercase tracking-wide">Pedido</th>
                  <th className="text-left p-3 font-semibold text-xs uppercase tracking-wide hidden md:table-cell">Cliente</th>
                  <th className="text-left p-3 font-semibold text-xs uppercase tracking-wide hidden lg:table-cell">Projeto</th>
                  <th className="text-left p-3 font-semibold text-xs uppercase tracking-wide">Status</th>
                  <th className="text-right p-3 font-semibold text-xs uppercase tracking-wide hidden sm:table-cell">Itens</th>
                  <th className="text-right p-3 font-semibold text-xs uppercase tracking-wide hidden md:table-cell">Criado em</th>
                  <th className="w-10"></th>
                </tr>
              </thead>
              <tbody>
                {ops.map((op) => {
                  const cfg = STATUS_CONFIG[op.status] || STATUS_CONFIG.aberta;
                  return (
                    <tr
                      key={op.id}
                      className="border-t hover:bg-accent/40 cursor-pointer"
                      onClick={() => navigate(`/ops/${op.id}`)}
                    >
                      <td className="p-3 font-mono font-semibold text-primary">{op.numero_op}</td>
                      <td className="p-3 font-mono text-xs text-muted-foreground">#{op.numero_pedido}</td>
                      <td className="p-3 hidden md:table-cell">
                        <div className="flex items-center gap-1.5">
                          <Building2 className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                          <span className="truncate max-w-[150px]">{op.cliente_nome || "—"}</span>
                        </div>
                      </td>
                      <td className="p-3 text-muted-foreground truncate max-w-[180px] hidden lg:table-cell">{op.project_name || "—"}</td>
                      <td className="p-3">
                        <Badge className={`${cfg.color} text-[10px]`}>{cfg.label}</Badge>
                      </td>
                      <td className="p-3 text-right text-muted-foreground mono-num hidden sm:table-cell">{(op.items || []).length}</td>
                      <td className="p-3 text-right text-muted-foreground hidden md:table-cell">{formatDateBR(op.created_at)}</td>
                      <td className="p-3 text-right">
                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
