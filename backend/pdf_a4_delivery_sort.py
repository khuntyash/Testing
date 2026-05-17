import fitz  # PyMuPDF

from partner_crop import detect_partner_for_page, get_clamped_partner_label_rect


def process_and_compile_labels(input_file_path, output_file_path):
    a4_width = 595.0
    a4_height = 842.0
    w2 = a4_width / 2.0
    h2 = a4_height / 2.0

    quadrants = [
        fitz.Rect(0, 0, w2, h2),
        fitz.Rect(w2, 0, a4_width, h2),
        fitz.Rect(0, h2, w2, a4_height),
        fitz.Rect(w2, h2, a4_width, a4_height),
    ]

    sorted_pages = {
        "Shadowfax": [],
        "ValmoPlus": [],
        "Valmo": [],
        "Delhivery": [],
        "Unknown": [],
    }

    with fitz.open(input_file_path) as src_doc:
        print("[meesho] Phase 1: analyzing and sorting labels...")
        for page in src_doc:
            partner = detect_partner_for_page(page)
            sorted_pages[partner].append(page.number)

        print("[meesho] Phase 2: compiling sorted labels into A4 format...")
        with fitz.open() as out_doc:
            label_count = 0
            out_page = None

            for partner, page_numbers in sorted_pages.items():
                if len(page_numbers) > 0:
                    print(f"   -> Formatting {len(page_numbers)} labels for {partner}")

                    for pno in page_numbers:
                        clip = get_clamped_partner_label_rect(src_doc[pno], partner)
                        quad_index = label_count % 4
                        if quad_index == 0:
                            out_page = out_doc.new_page(width=a4_width, height=a4_height)

                        out_page.show_pdf_page(
                            rect=quadrants[quad_index],
                            docsrc=src_doc,
                            pno=pno,
                            clip=clip,
                            rotate=90,
                        )
                        label_count += 1

            out_doc.save(output_file_path)

            print(f"[meesho] Success: sorted and processed {label_count} total labels.")
            print(f"[meesho] Created A4 PDF with {len(out_doc)} pages.")
            print(f"[meesho] Saved to: {output_file_path}")


if __name__ == "__main__":
    my_input_pdf = r"D:\Gate\Sub_Order_Labels_87fb0f8e-81e2-4ea3-9b75-ab84c1451c88.pdf"
    my_output_pdf = r"D:\Gate\final_sorted_A4_labels.pdf"

    try:
        process_and_compile_labels(my_input_pdf, my_output_pdf)
    except FileNotFoundError:
        print(f"[meesho] Error: could not find the file '{my_input_pdf}'.")
    except Exception as e:
        print(f"[meesho] Unexpected error: {e}")
