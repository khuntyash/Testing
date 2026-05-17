import fitz  # PyMuPDF

from partner_crop import detect_partner_for_page, get_clamped_partner_label_rect


def crop_rotate_and_combine(input_file_path, output_file_path):
    with fitz.open(input_file_path) as src_doc:
        with fitz.open() as out_doc:
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

            out_page = None

            for i, page in enumerate(src_doc):
                partner = detect_partner_for_page(page)
                label_rect = get_clamped_partner_label_rect(page, partner)

                quad_index = i % 4
                if quad_index == 0:
                    out_page = out_doc.new_page(width=a4_width, height=a4_height)

                out_page.show_pdf_page(
                    rect=quadrants[quad_index],
                    docsrc=src_doc,
                    pno=page.number,
                    clip=label_rect,
                    rotate=90,
                )

            out_doc.save(output_file_path)

            print(f"[meesho] Successfully processed {len(src_doc)} labels.")
            print(f"[meesho] Created A4 PDF with {len(out_doc)} pages.")
            print(f"[meesho] Saved to: {output_file_path}")


if __name__ == "__main__":
    my_input_pdf = r"D:\Gate\Sub_Order_Labels_87fb0f8e-81e2-4ea3-9b75-ab84c1451c88.pdf"
    my_output_pdf = r"D:\Gate\final_A4_combined_labels.pdf"

    crop_rotate_and_combine(my_input_pdf, my_output_pdf)
