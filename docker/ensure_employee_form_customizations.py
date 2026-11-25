import json

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


SETTINGS = [
    {
        "field_name": "middle_name",
        "property": "hidden",
        "value": "1",
        "property_type": "Check",
        "for_doctype": False,
    },
    {
        "field_name": "salutation",
        "property": "hidden",
        "value": "1",
        "property_type": "Check",
        "for_doctype": False,
    },
    {
        "field_name": "last_name",
        "property": "hidden",
        "value": "1",
        "property_type": "Check",
        "for_doctype": False,
    },
    {
        "field_name": None,
        "property": "show_title_field_in_link",
        "value": "1",
        "property_type": "Check",
        "for_doctype": True,
    },
]


def ensure_employee_form_customizations():
    result = {"created": [], "updated": [], "unchanged": []}

    for setting in SETTINGS:
        doctype_or_field = "DocType" if setting["for_doctype"] else "DocField"
        filters = {
            "doc_type": "Employee",
            "doctype_or_field": doctype_or_field,
            "property": setting["property"],
        }
        if setting["field_name"]:
            filters["field_name"] = setting["field_name"]

        existing = frappe.get_all(
            "Property Setter",
            filters=filters,
            fields=["name", "value", "property_type"],
            order_by="creation asc",
        )
        label = setting["field_name"] or "DocType"

        if len(existing) > 1:
            frappe.throw(
                f"Duplicate Property Setter for Employee {label} {setting['property']}: "
                + ", ".join(row.name for row in existing)
            )

        if not existing:
            make_property_setter(
                "Employee",
                setting["field_name"],
                setting["property"],
                setting["value"],
                setting["property_type"],
                for_doctype=setting["for_doctype"],
            )
            result["created"].append(label)
            continue

        property_setter = frappe.get_doc("Property Setter", existing[0].name)
        if (
            property_setter.value != setting["value"]
            or property_setter.property_type != setting["property_type"]
        ):
            property_setter.value = setting["value"]
            property_setter.property_type = setting["property_type"]
            property_setter.save(ignore_permissions=True)
            result["updated"].append(label)
        else:
            result["unchanged"].append(label)

    frappe.clear_cache()
    return result


result = ensure_employee_form_customizations()
print(json.dumps(result, ensure_ascii=False))
