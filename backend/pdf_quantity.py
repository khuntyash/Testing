import fitz  # PyMuPDF
import re

from partner_crop import detect_partner_for_page, get_clamped_partner_label_rect


def extract_quantity(full_text):
    table_matches = re.findall(r"\b(\d{1,3})[\s\n]+Rs\.?\s*\d+", full_text, re.IGNORECASE)
    if table_matches:
        total_qty = sum(int(qty) for qty in table_matches)
        if total_qty > 0:
            return total_qty

    linear_match = re.search(r"(?:qty|quantity|pcs|items?)[\s:]*(\d+)", full_text, re.IGNORECASE)
    if linear_match:
        return int(linear_match.group(1))

    return 1


def sort_and_crop_labels(input_file_path, output_file_path):
    single_qty_pages = {
        "Shadowfax": [],
        "ValmoPlus": [],
        "Valmo": [],
        "Delhivery": [],
        "Unknown": [],
    }
    multi_qty_pages = {
        "Shadowfax": [],
        "ValmoPlus": [],
        "Valmo": [],
        "Delhivery": [],
        "Unknown": [],
    }

    print("[meesho] Analyzing pages...")
    with fitz.open(input_file_path) as original_doc:
        for page_num in range(len(original_doc)):
            page = original_doc[page_num]
            full_page_text = page.get_text("text")
            qty = extract_quantity(full_page_text)

            partner = detect_partner_for_page(page)
            label_rect = get_clamped_partner_label_rect(page, partner)
            page.set_cropbox(label_rect)
            print(f"   -> Page {page_num + 1}: {partner} | Qty: {qty}")

            if qty > 1:
                multi_qty_pages[partner].append(page_num)
            else:
                single_qty_pages[partner].append(page_num)

        print("[meesho] Sorting document...")
        with fitz.open() as sorted_doc:
            for partner, page_numbers in single_qty_pages.items():
                if len(page_numbers) > 0:
                    for p_num in page_numbers:
                        sorted_doc.insert_pdf(original_doc, from_page=p_num, to_page=p_num)

            for partner, page_numbers in multi_qty_pages.items():
                if len(page_numbers) > 0:
                    for p_num in page_numbers:
                        sorted_doc.insert_pdf(original_doc, from_page=p_num, to_page=p_num)

            print("[meesho] Saving file...")
            sorted_doc.save(output_file_path)
            print(f"[meesho] Success: sorted and cropped {len(sorted_doc)} total pages.")
            print(
                f"   (Single Qty: {sum(len(v) for v in single_qty_pages.values())} | Multi Qty: {sum(len(v) for v in multi_qty_pages.values())})"
            )


if __name__ == "__main__":
    my_input_pdf = r"D:\Gate\Sub_Order_Labels_87fb0f8e-81e2-4ea3-9b75-ab84c1451c88.pdf"
    my_output_pdf = r"D:\Gate\1sorted_and_cropped_labels.pdf"

    try:
        sort_and_crop_labels(my_input_pdf, my_output_pdf)
    except FileNotFoundError:
        print(f"[meesho] Error: could not find the file '{my_input_pdf}'.")
    except Exception as e:
        print(f"[meesho] Unexpected error: {e}")
