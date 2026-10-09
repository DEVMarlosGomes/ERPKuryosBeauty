import { useMemo, useState } from "react";
import { Archive } from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import SectorLegacyReviewPanel from "@/components/legacy/SectorLegacyReviewPanel";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const ALL_SECTORS = [
  ["pcp", "PCP"],
  ["logistica", "Logística"],
  ["comercial", "Comercial"],
  ["cadastros", "Cadastros"],
  ["expedicao", "Expedição"],
  ["qualidade", "Qualidade"],
  ["pd", "P&D"],
  ["compras", "Compras"],
  ["administracao_ti", "Administração / TI"],
  ["rh", "RH"],
];

const ROLE_SECTORS = {
  pcp: ["pcp"],
  producao: ["pcp"],
  vendedor: ["comercial", "cadastros"],
  sales_ops: ["comercial", "cadastros", "pcp", "qualidade"],
  sucesso_cliente: ["comercial", "cadastros"],
  compras: ["compras", "cadastros", "logistica", "qualidade"],
  qa: ["qualidade", "cadastros", "logistica"],
  lider_pd: ["pd", "qualidade", "cadastros", "pcp", "logistica"],
  formulador: ["pd", "qualidade", "cadastros", "logistica"],
  engenharia_produto: ["pd", "qualidade", "cadastros", "compras", "pcp", "logistica"],
  logistica: ["logistica", "expedicao"],
  estoque: ["logistica"],
  faturamento: ["expedicao"],
  gestor: ["pcp", "comercial", "cadastros"],
};

export default function ReviewSectorPage() {
  const { user } = useAuth();
  const allowed = useMemo(() => {
    const keys = user?.role === "admin" ? ALL_SECTORS.map(([key]) => key) : (ROLE_SECTORS[user?.role] || []);
    return ALL_SECTORS.filter(([key]) => keys.includes(key));
  }, [user?.role]);
  const [selected, setSelected] = useState(null);
  const sector = allowed.some(([key]) => key === selected) ? selected : allowed[0]?.[0];

  return (
    <div className="min-h-screen space-y-5 p-4 md:p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold"><Archive className="h-6 w-6 text-amber-500" />Revisões da migração</h1>
          <p className="mt-1 text-sm text-muted-foreground">Dados legados organizados por setor, com conferência completa, encaminhamento e trilha de auditoria.</p>
        </div>
        {allowed.length > 1 && <Select value={sector} onValueChange={setSelected}><SelectTrigger className="w-full md:w-64"><SelectValue /></SelectTrigger><SelectContent>{allowed.map(([key, label]) => <SelectItem key={key} value={key}>{label}</SelectItem>)}</SelectContent></Select>}
      </div>
      {sector ? <SectorLegacyReviewPanel sector={sector} /> : <div className="rounded-lg border p-8 text-center text-muted-foreground">Seu perfil não possui uma fila setorial de migração.</div>}
    </div>
  );
}
