// Хялбаршуулсан горимын тойм (1%) — the quarter is derived from to_date; simulation shows unverified rates.
frappe.query_reports["Nyabo Simplified Tax Summary"] = {
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
			default: frappe.datetime.quarter_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.quarter_end(),
			reqd: 1,
		},
		{
			fieldname: "simulation",
			label: __("Simulation"),
			fieldtype: "Check",
			default: 0,
		},
	],
};
