/** @odoo-module **/
import * as owlApi from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
const { Component, onWillStart } = owlApi;
const useState = owlApi.useState || owlApi.proxy;
const COPY = {
    zh: {title: "我的方案核实", intro: "查看分派给自己的核实事项，直接进入共同方案反馈。", pending: "待核实", done: "已完成", refresh: "刷新", open: "打开共同方案", empty: "当前没有待核实事项。收到分派后会显示在这里。", emptyDone: "还没有已完成的核实事项。", loading: "正在读取…", error: "暂时无法读取核实事项，请刷新重试。", changed: "该事项可能已重新分派或公司范围已变化，请刷新列表。", due: "核实期限", more: "仅显示前 200 项，请及时处理或联系计划员。", met: "本项安排可落实", notMet: "本项安排不可落实", unknown: "已完成，结论待补充"},
    en: {title: "My plan reviews", intro: "Open your assigned reviews directly in the shared plan.", pending: "Pending", done: "Completed", refresh: "Refresh", open: "Open shared plan", empty: "No pending reviews. Assigned reviews will appear here.", emptyDone: "No completed reviews yet.", loading: "Loading…", error: "Unable to load reviews. Please refresh.", changed: "The assignment or company scope may have changed. Refresh the list.", due: "Review due", more: "Showing the first 200 reviews.", met: "Arrangement feasible", notMet: "Arrangement not feasible", unknown: "Completed; conclusion missing"},
    fr: {title: "Mes vérifications de plans", intro: "Ouvrez vos vérifications directement dans le plan partagé.", pending: "À vérifier", done: "Terminées", refresh: "Actualiser", open: "Ouvrir le plan partagé", empty: "Aucune vérification en attente.", emptyDone: "Aucune vérification terminée.", loading: "Chargement…", error: "Lecture impossible. Veuillez actualiser.", changed: "L’affectation ou la société a changé. Actualisez la liste.", due: "Échéance", more: "Les 200 premières vérifications sont affichées.", met: "Disposition réalisable", notMet: "Disposition non réalisable", unknown: "Terminée ; conclusion manquante"},
};
function copy() { return COPY[(user.context.lang || "en").slice(0, 2)] || COPY.en; }
export class ReviewInbox extends Component {
    static template = "material_delay_impact.ReviewInbox";
    static props = ["*"];
    setup() {
        this.orm = useService("orm"); this.action = useService("action");
        this.words = copy(); this.state = useState({items: [], completed: false, busy: false, error: "", truncated: false});
        onWillStart(() => this.load());
    }
    async load(completed = this.state.completed) {
        if (this.state.busy) return;
        this.state.busy = true; this.state.error = ""; this.state.completed = completed;
        try { const value = await this.orm.call("mail.activity", "mdic_my_reviews", [], {completed}); this.state.items = value.items; this.state.truncated = value.truncated; }
        catch { this.state.items = []; this.state.error = this.words.error; }
        finally { this.state.busy = false; }
    }
    async open(item) {
        if (this.state.busy) return;
        this.state.busy = true; this.state.error = "";
        try { await this.action.doAction(await this.orm.call("mail.activity", "mdic_open_my_review", [item.id])); }
        catch { this.state.error = this.words.changed; }
        finally { this.state.busy = false; }
    }
    status(item) { return !item.done ? this.words.pending : item.outcome === "met" ? this.words.met : item.outcome === "not_met" ? this.words.notMet : this.words.unknown; }
}
export class ReviewShortcut extends Component {
    static template = "material_delay_impact.ReviewShortcut";
    static props = ["*"];
    setup() { this.action = useService("action"); this.words = copy(); }
    open() { return this.action.doAction("material_delay_impact.mdic_my_reviews_action"); }
}
registry.category("actions").add("mdic_my_reviews", ReviewInbox);
registry.category("systray").add("material_delay_impact.reviews", {Component: ReviewShortcut}, {sequence: 35});
