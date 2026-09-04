import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Bell, CheckCheck, Sparkles, Flame, UserPlus, Zap, ListTodo } from "lucide-react";

const ICONS = {
    automation: Zap,
    hot_lead: Flame,
    user_invited: UserPlus,
    ai: Sparkles,
    workflow_task: ListTodo,
};

export default function NotificationPanel() {
    const [notifications, setNotifications] = useState([]);
    const [unread, setUnread] = useState(0);
    const [open, setOpen] = useState(false);

    const loadNotifications = useCallback(async () => {
        try {
            const [{ data: notifs }, { data: count }] = await Promise.all([
                api.get("/notifications"),
                api.get("/notifications/count")
            ]);
            setNotifications(notifs);
            setUnread(count.count);
        } catch {}
    }, []);

    useEffect(() => {
        loadNotifications();
        const interval = setInterval(loadNotifications, 15000);
        return () => clearInterval(interval);
    }, [loadNotifications]);

    const markAllRead = async () => {
        try {
            await api.put("/notifications/read-all");
            setUnread(0);
            setNotifications(prev => prev.map(n => ({ ...n, read: true })));
        } catch {}
    };

    const markRead = async (id) => {
        try {
            await api.put(`/notifications/${id}/read`);
            setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
            setUnread(prev => Math.max(0, prev - 1));
        } catch {}
    };

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <button className="relative flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:bg-muted/80 hover:text-foreground"
                    data-testid="notifications-btn">
                    <Bell className="h-4 w-4 shrink-0" />
                    Notificações
                    {unread > 0 && (
                        <span className="absolute top-1.5 left-6 h-4 min-w-[16px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center"
                            data-testid="unread-badge">{unread}</span>
                    )}
                </button>
            </PopoverTrigger>
            <PopoverContent side="right" align="start" className="w-80 p-0" data-testid="notifications-panel">
                <div className="p-3 border-b flex items-center justify-between">
                    <h3 className="font-heading font-medium text-sm">Notificações</h3>
                    {unread > 0 && (
                        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={markAllRead} data-testid="mark-all-read">
                            <CheckCheck className="h-3 w-3 mr-1" /> Marcar todas lidas
                        </Button>
                    )}
                </div>
                <ScrollArea className="max-h-80">
                    {notifications.length === 0 ? (
                        <p className="text-sm text-muted-foreground text-center py-6">Sem notificacoes</p>
                    ) : (
                        <div className="divide-y">
                            {notifications.map(n => {
                                const Icon = ICONS[n.type] || Bell;
                                return (
                                    <button key={n.id} onClick={() => markRead(n.id)}
                                        className={`w-full text-left p-3 hover:bg-accent transition-colors ${!n.read ? "bg-accent/30" : ""}`}
                                        data-testid={`notification-${n.id}`}>
                                        <div className="flex gap-2.5">
                                            <Icon className={`h-4 w-4 shrink-0 mt-0.5 ${!n.read ? "text-primary" : "text-muted-foreground"}`} />
                                            <div className="min-w-0">
                                                <p className={`text-xs font-medium ${!n.read ? "" : "text-muted-foreground"}`}>{n.title}</p>
                                                <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">{n.message}</p>
                                                <p className="text-[10px] text-muted-foreground mt-1 mono-num">
                                                    {new Date(n.created_at).toLocaleString("pt-BR")}
                                                </p>
                                            </div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </ScrollArea>
            </PopoverContent>
        </Popover>
    );
}
