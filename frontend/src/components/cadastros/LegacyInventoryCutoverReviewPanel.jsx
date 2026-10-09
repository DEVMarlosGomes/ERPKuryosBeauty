import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Eye, RefreshCw, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import LegacyStructuredFields from "@/components/legacy/LegacyStructuredFields";

function Stat({ label, value }) {
  return <Card><CardContent className="p-4"><p className="text-xs uppercase text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold">{value || 0}</p></CardContent></Card>;
}

export default function LegacyInventoryCutoverReviewPanel({ globalSearch = "" }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({});
  const [recordType, setRecordType] = useState("todos");
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get("/cadastros/revisoes-corte-estoque", {
        params: { record_type: recordType, q: globalSearch || undefined, limit: 300 },
      });
      setRows(response.data.registros || []);
      setSummary(response.data.resumo || {});
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erro ao carregar a revisão do corte físico.");
    } finally {
      setLoading(false);
    }
  }, [globalSearch, recordType]);

  useEffect(() => {
    const timer = window.setTimeout(load, 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  const openDetail = async (row) => {
    try {
      const response = await api.get(`/cadastros/revisoes-corte-estoque/${row.id}`);
      setDetail(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível abrir o registro.");
    }
  };

  return <div className="space-y-4">
    <div>
      <h3 className="flex items-center gap-2 text-lg font-semibold"><ShieldAlert className="h-5 w-5 text-amber-500" /> Corte físico legado — somente leitura</h3>
      <p className="text-sm text-muted-foreground">Endereços e lotes importados para conferência. Esta fila não cria saldo, ledger, reserva, palete ou endereço operacional.</p>
    </div>
    <div className="grid gap-3 sm:grid-cols-3">
      <Stat label="Total bloqueado" value={summary.blocked} />
      <Stat label="Endereços" value={summary.address} />
      <Stat label="Lotes" value={summary.lot} />
    </div>
    <Card>
      <CardHeader className="pb-3"><div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <CardTitle className="flex-1 text-base">Fila para conferência física</CardTitle>
        <Select value={recordType} onValueChange={setRecordType}><SelectTrigger className="w-full sm:w-52"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="todos">Todos</SelectItem><SelectItem value="address">Endereços</SelectItem><SelectItem value="lot">Lotes</SelectItem></SelectContent></Select>
        <Button variant="outline" onClick={load} disabled={loading} className="gap-2"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} /> Atualizar</Button>
      </div></CardHeader>
      <CardContent><div className="overflow-x-auto rounded-md border"><Table>
        <TableHeader><TableRow><TableHead>Tipo</TableHead><TableHead>Código/lote</TableHead><TableHead>Material/área</TableHead><TableHead>Endereço</TableHead><TableHead>Saldo legado</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
        <TableBody>{rows.map((row) => <TableRow key={row.id}>
          <TableCell><Badge variant="outline">{row.record_type === "address" ? "Endereço" : "Lote"}</Badge></TableCell>
          <TableCell className="font-mono text-xs">{row.legacy_code}</TableCell>
          <TableCell>{row.legacy_name || row.legacy_material_code || "-"}</TableCell>
          <TableCell className="font-mono text-xs">{row.legacy_address_code || (row.record_type === "address" ? row.legacy_code : "-")}</TableCell>
          <TableCell>{row.record_type === "lot" ? `${row.legacy_quantity ?? "-"} ${row.legacy_unit || ""}` : "-"}</TableCell>
          <TableCell><Badge variant="secondary">{String(row.physical_status || "não conferido").replaceAll("_", " ")}</Badge></TableCell>
          <TableCell><Button size="icon" variant="ghost" onClick={() => openDetail(row)} title="Ver origem"><Eye className="h-4 w-4" /></Button></TableCell>
        </TableRow>)}
        {!rows.length && <TableRow><TableCell colSpan={7} className="py-8 text-center text-muted-foreground">{loading ? "Carregando..." : "Nenhum registro encontrado."}</TableCell></TableRow>}
        </TableBody>
      </Table></div></CardContent>
    </Card>
    <Dialog open={Boolean(detail)} onOpenChange={(open) => !open && setDetail(null)}><DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
      <DialogHeader><DialogTitle>Origem do corte — {detail?.legacy_code}</DialogTitle></DialogHeader>
      {detail && <div className="space-y-3 text-sm">
        <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3">Bloqueado até conferência física, validação de CQ/WMS e autorização de corte.</div>
        <p><strong>Motivo:</strong> {detail.reason}</p><p><strong>Decisão necessária:</strong> {String(detail.required_decision || "").replaceAll("_", " ")}</p>
        <LegacyStructuredFields data={detail.source_payload || {}} />
      </div>}
    </DialogContent></Dialog>
  </div>;
}
