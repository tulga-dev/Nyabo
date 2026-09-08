// Мөнгөн гүйлгээний журнал (МГ-1 / МГ-2) — filters: company, from_date, to_date, optional account.
frappe.query_reports["Nyabo Cash Journal"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			fieldname: "account",
			label: __("Account"),
			fieldtype: "Link",
			options: "Account",
			get_query: function () {
				return { filters: { account_type: ["in", ["Cash", "Bank"]], is_group: 0 } };
			},
		},
	],
};
