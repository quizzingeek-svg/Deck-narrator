"""Create samples/sample_deck.pptx: a 6-slide market-entry deck with a table, a chart and notes on some slides."""
from pathlib import Path
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent.parent / "samples" / "sample_deck.pptx"


def bullets(slide, items):
    body = slide.placeholders[1].text_frame
    body.text = items[0]
    for it in items[1:]:
        lvl = 1 if it.startswith("  ") else 0
        p = body.add_paragraph(); p.text = it.strip(); p.level = lvl


def main():
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Entering India's Diagnostic Imaging Market"
    s.placeholders[1].text = "Market sizing & go-to-market plan | Board review, Q3 FY26"
    s.notes_slide.notes_text_frame.text = (
        "Good morning everyone. Today I want to walk you through why we think India's diagnostic imaging "
        "market is the right next bet for us, how big the prize is, and what it will take to win.")

    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Why now: demand is outpacing capacity"
    bullets(s, ["Only ~1.5 CT scanners per million people vs 40+ in the US",
                "Ayushman Bharat covers 500M+ people, pushing diagnostic volumes up",
                "Tier-2/3 cities: 60% of new hospital beds since 2020",
                "  Most lack MRI/CT within 50 km",
                "Private chains (Dr Lal, Metropolis) expanding into imaging"])

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Market size: USD 1.6B growing at ~9% CAGR"
    cd = CategoryChartData()
    cd.categories = ["2022", "2023", "2024", "2025E", "2026E", "2028E", "2030E"]
    cd.add_series("Market size (USD M)", (1180, 1290, 1410, 1540, 1680, 2000, 2380))
    ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.7), Inches(1.6), Inches(8), Inches(5.2), cd).chart
    ch.has_title = True; ch.chart_title.text_frame.text = "India diagnostic imaging market (USD M)"
    tb = s.shapes.add_textbox(Inches(9), Inches(2), Inches(4), Inches(3)).text_frame
    tb.text = "CT & MRI = 55% of value"; tb.add_paragraph().text = "Ultrasound fastest at 11% CAGR"
    s.notes_slide.notes_text_frame.text = (
        "The market is about 1.4 billion dollars today and should cross 2.3 billion by 2030. "
        "The point to take away is that growth is steady, not a bubble, and the fastest piece is ultrasound.")

    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Competitive landscape"
    rows = [["Player", "Share", "Strength", "Gap"],
            ["GE HealthCare", "28%", "Installed base, service", "Premium pricing"],
            ["Siemens Healthineers", "24%", "High-end MRI", "Weak in Tier-3"],
            ["Philips", "18%", "Ultrasound, AI tools", "Service coverage"],
            ["Local OEMs", "12%", "Price", "Image quality"],
            ["Others", "18%", "-", "-"]]
    t = s.shapes.add_table(len(rows), 4, Inches(0.7), Inches(1.7), Inches(12), Inches(4)).table
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            t.cell(r, c).text = val
            t.cell(r, c).text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    # no notes on this slide on purpose

    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Our go-to-market plan"
    bullets(s, ["Phase 1 (FY26): refurbished CT on pay-per-scan in 40 Tier-2 cities",
                "Phase 2 (FY27): AI-assisted ultrasound bundles for clinics",
                "Phase 3 (FY28): service network covering 90% of installed base",
                "Partner with 2 diagnostic chains for guaranteed volume"])
    s.notes_slide.notes_text_frame.text = (
        "We go in three phases. Start where the gap is biggest, Tier-2 CT, with a pay-per-scan model so hospitals "
        "don't need capex. Then add ultrasound, then build the service moat.")

    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "The ask"
    bullets(s, ["USD 45M over 3 years", "Break-even in month 30", "Target 8% market share by FY29",
                "Decision needed today: approve Phase 1 (USD 12M)"])
    # default layouts are 4:3; stretch title/body placeholders to the 16:9 width
    for sl in prs.slides:
        for ph in sl.placeholders:
            top, height = ph.top, ph.height          # inherited from the layout
            if sl.slide_layout == prs.slide_layouts[0]:
                top, height = (Inches(2.0), Inches(1.6)) if ph.placeholder_format.idx == 0 else (Inches(3.9), Inches(1.2))
            elif ph.placeholder_format.idx == 0:
                top, height = Inches(0.35), Inches(1.1)
            else:
                top, height = Inches(1.6), Inches(5.3)
            ph.left, ph.top, ph.width, ph.height = Inches(0.7), top, Inches(11.9), height
    prs.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
