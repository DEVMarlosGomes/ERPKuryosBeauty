import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Eye, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import LegacyStructuredFields from "@/components/legacy/LegacyStructuredFields";

const labels = {
  commercial_order: "Pedidos comerciais",
  order_line: "Itens de pedido",
  production_order: "Ordens de produção",
  archive_ready: "Pronto para arquivo",
  historical_archive_ready: "Histórico conciliado",
  manual_review: "Revisão manual",
  open_requires_decision: "OP aberta — decidir",
};

function Stat({ label, value }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs uppercase text-muted-foreground">{label}</p>
        <p className="mt-1 text-2xl font-semibold">{value || 0}</p>
      </CardContent>
    </Card>
  );
}

export default function LegacyOrderOpReviewPanel({ globalSearch = "" }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [recordType, setRecordType] = useState("commercial_order");
  const [classification, setClassification] = useState("todos");
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get("/cadastros/revisoes-pedidos-ops", {
        params: {
          record_type: recordType,
          classification,
          q: globalSearch || undefined,
          limit: 250,
        },
      });
      setRows(response.data.registros || []);
      setSummary(response.data.resumo || {});
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao carregar pedidos e OPs legados.");
    } finally {
      setLoading(false);
    }
  }, [classification, globalSearch, recordType]);

  useEffect(() => {
    const timer = window.setTimeout(load, 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  const openDetail = async (row) => {
    try {
      const response = await api.get(`/cadastros/revisoes-pedidos-ops/${row.id}`);
      setDetail(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível abrir a revisão.");
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">Pedidos e OPs importados para revisão</h3>
        <p className="text-sm text-muted-foreground">
          Registros históricos isolados. Nenhum deles movimenta estoque, reserva material ou inicia produção.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat label="Pedidos" value={summary.commercial_order} />
        <Stat label="Itens" value={summary.order_line} />
        <Stat label="OPs" value={summary.production_order} />
        <Stat label="Revisão manual" value={summary.manual_review} />
        <Stat label="OPs abertas" value={summary.open_requires_decision} />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <CardTitle className="flex-1 text-base">Fila bloqueada de homologação</CardTitle>
            <Select value={recordType} onValueChange={setRecordType}>
              <SelectTrigger className="w-full sm:w-52"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="commercial_order">Pedidos comerciais</SelectItem>
                <SelectItem value="order_line">Itens de pedido</SelectItem>
                <SelectItem value="production_order">Ordens de produção</SelectItem>
              </SelectContent>
            </Select>
            <Select value={classification} onValueChange={setClassification}>
              <SelectTrigger className="w-full sm:w-52"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todas as classificações</SelectItem>
                <SelectItem value="archive_ready">Pronto para arquivo</SelectItem>
                <SelectItem value="historical_archive_ready">Histórico conciliado</SelectItem>
                <SelectItem value="manual_review">Revisão manual</SelectItem>
                <SelectItem value="open_requires_decision">OP aberta — decidir</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" onClick={load} disabled={loading} className="gap-2">
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Atualizar
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Origem</TableHead><TableHead>Tipo</TableHead><TableHead>Status legado</TableHead>
                  <TableHead>SKU</TableHead><TableHead>Classificação</TableHead><TableHead>Bloqueios</TableHead><TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="font-mono text-xs">{row.source_key}</TableCell>
                    <TableCell>{labels[row.record_type] || row.record_type}</TableCell>
                    <TableCell>{row.legacy_status || "-"}</TableCell>
                    <TableCell className="font-mono text-xs">{row.target_sku_code || "Não resolvido"}</TableCell>
                    <TableCell><Badge variant="outline">{labels[row.reconciliation_classification] || row.reconciliation_classification}</Badge></TableCell>
                    <TableCell>{(row.blockers || []).length}</TableCell>
                    <TableCell><Button size="icon" variant="ghost" onClick={() => openDetail(row)}><Eye className="h-4 w-4" /></Button></TableCell>
                  </TableRow>
                ))}
                {!rows.length && <TableRow><TableCell colSpan={7} className="py-8 text-center text-muted-foreground">{loading ? "Carregando..." : "Nenhum registro encontrado."}</TableCell></TableRow>}
              </TableBody>
            </Table>
          </div>
          {rows.length === 250 && <p className="mt-2 text-xs text-muted-foreground">Exibindo os primeiros 250 registros. Use busca e filtros para refinar.</p>}
        </CardContent>
      </Card>

      <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
          <DialogHeader><DialogTitle>Registro legado — {detail?.source_key}</DialogTitle></DialogHeader>
          {detail && (
            <div className="space-y-3 text-sm">
              <div className="grid gap-2 sm:grid-cols-2">
                <p><strong>Tipo:</strong> {labels[detail.record_type] || detail.record_type}</p>
                <p><strong>Status:</strong> {detail.legacy_status || "-"}</p>
                <p><strong>Classificação:</strong> {labels[detail.reconciliation_classification] || detail.reconciliation_classification}</p>
                <p><strong>Ativação:</strong> {detail.activation_status}</p>
              </div>
              <LegacyStructuredFields data={{ bloqueios: detail.blockers || [], conciliacao: detail.reconciliation || {} }} />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
