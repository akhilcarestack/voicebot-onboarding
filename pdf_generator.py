from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.units import mm
from io import BytesIO
from datetime import datetime
from xml.sax.saxutils import escape

# Define Premium Dark Palette
BG_COLOR = colors.HexColor("#07070d")
CARD_BG = colors.HexColor("#121220")
HEADER_BG = colors.HexColor("#16162a")
TEAL = colors.HexColor("#00d4aa")
ROSE = colors.HexColor("#f43f5e")
AMBER = colors.HexColor("#f59e0b")
TEXT_COLOR = colors.HexColor("#f0f0f5")
TEXT_SEC = colors.HexColor("#8b8ba3")
BORDER_COLOR = colors.HexColor("#28283c")


def _id_key(value) -> str:
    if value is None:
        return ""
    return str(value)


def _get_by_id(mapping: dict, value, default=None):
    key = _id_key(value)
    if key in mapping:
        return mapping[key]
    try:
        int_key = int(value)
    except (TypeError, ValueError):
        return default
    return mapping.get(int_key, default)


def _ids_for(mapping: dict, value) -> list:
    item = _get_by_id(mapping, value, [])
    return item if isinstance(item, list) else []


def _name_list(names: list, empty="--") -> str:
    names = [str(name) for name in names if name]
    return ", ".join(names) if names else empty


def _limited_name_list(names: list, limit=12, empty="--") -> str:
    names = [str(name) for name in names if name]
    if not names:
        return empty
    shown = names[:limit]
    remainder = len(names) - len(shown)
    suffix = f", and {remainder} more" if remainder > 0 else ""
    return ", ".join(shown) + suffix


def generate_config_pdf(data: dict) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=landscape(A4),
        rightMargin=12*mm, leftMargin=12*mm,
        topMargin=12*mm, bottomMargin=12*mm
    )

    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=TEAL,
        alignment=1, # Center
        leading=28,
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        'SubtitleStyle',
        fontSize=10.5,
        textColor=TEXT_SEC,
        alignment=1,
        leading=13,
        spaceAfter=20
    )
    
    section_header_style = ParagraphStyle(
        'SectionHeader',
        fontSize=14,
        textColor=TEAL,
        backColor=HEADER_BG,
        borderPadding=5,
        spaceBefore=15,
        spaceAfter=10,
        leading=18
    )

    body_style = ParagraphStyle(
        'BodyText',
        fontSize=10.5,
        textColor=TEXT_COLOR,
        leading=14,
        wordWrap='CJK'
    )
    small_style = ParagraphStyle(
        'SmallText',
        parent=body_style,
        fontSize=9,
        leading=11,
        wordWrap='CJK'
    )
    table_cell_style = ParagraphStyle(
        'TableCell',
        parent=small_style,
        fontSize=8.2,
        leading=9.5,
        wordWrap='CJK'
    )
    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=table_cell_style,
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=9,
        textColor=TEAL,
        wordWrap='CJK'
    )
    tiny_cell_style = ParagraphStyle(
        'TinyTableCell',
        parent=table_cell_style,
        fontSize=7.2,
        leading=8.2,
        wordWrap='CJK'
    )

    elements = []
    table_width = min(doc.width, 260*mm)

    def cell(value, style=table_cell_style, empty="--"):
        if isinstance(value, Paragraph):
            return value
        if value is None or value == "":
            value = empty
        return Paragraph(escape(str(value)), style)

    def header_cell(value):
        return cell(value, table_header_style)

    selected_locations = data.get('selectedLocations', []) or []
    loc_lookup = {
        _id_key(loc.get('id')): loc.get('name') or f"Location #{loc.get('id')}"
        for loc in selected_locations
        if loc.get('id') is not None
    }

    # Background implementation
    def add_page_background(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BG_COLOR)
        canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], fill=1)
        canvas.restoreState()

    # 1. Title
    elements.append(Paragraph("VoiceBot PMS Configuration Report", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", subtitle_style))

    # 2. Config Info
    bot_enabled_text = '<font color="#00d4aa">Yes</font>' if data.get('botEnabled') else '<font color="#f43f5e">No</font>'
    config_data = [
        [Paragraph(f"<b>Locations:</b> {escape(', '.join(data.get('selectedLocNames', [])))}", body_style),
         Paragraph(f"<b>Bot Enabled:</b> {bot_enabled_text}", body_style)],
        [Paragraph(f"<b>Excluded Insurance:</b> {escape(data.get('excludedInsText') or 'None')}", body_style),
         Paragraph(f"<b>Notes:</b> {escape(data.get('notesText') or 'None')}", body_style)]
    ]
    config_table = Table(config_data, colWidths=[table_width / 2, table_width / 2])
    config_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
        ('BOX', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('PADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(config_table)
    elements.append(Spacer(1, 10*mm))

    # 3. Selected Providers
    providers = data.get('selectedProviders', [])
    provider_lookup = {_id_key(p.get('id')): p for p in providers}
    all_prov_map = data.get('all_provider_name_map', {}) or {}
    for pid, p_info in all_prov_map.items():
        provider_lookup.setdefault(_id_key(pid), p_info)

    pts = data.get('selectedPTs', [])
    all_pts = data.get('allProductionTypes', []) or []
    pt_lookup = {_id_key(pt.get('id')): pt for pt in all_pts}
    for pt in pts:
        pt_lookup[_id_key(pt.get('id'))] = pt
    ops = data.get('operatories', []) or []
    op_lookup = {_id_key(op.get('id')): op for op in ops}

    def provider_label(pid):
        p_info = _get_by_id(provider_lookup, pid)
        if not p_info:
            return f"ID:{pid}"
        name = p_info.get('name') or f"ID:{pid}"
        conc = p_info.get('concurrency')
        if conc not in (None, "", "N/A"):
            return f"{name} ({conc})"
        return name

    def production_type_label(ptid):
        pt_obj = _get_by_id(pt_lookup, ptid)
        if not pt_obj:
            return f"ID:{ptid}"
        return pt_obj.get('name') or f"ID:{ptid}"

    def location_label(lid):
        loc_name = _get_by_id(loc_lookup, lid)
        if loc_name:
            return loc_name
        return f"Location #{lid}"

    def operatory_label(opid):
        op_obj = _get_by_id(op_lookup, opid)
        if not op_obj:
            return f"Op #{opid}"
        op_name = op_obj.get('name') or f"Op #{opid}"
        return f"{op_name} (#{opid})"

    elements.append(Paragraph(f"Selected Providers ({len(providers)})", section_header_style))
    if providers:
        p_head = [header_cell(x) for x in ['ID', 'Name', 'Type', 'Specialty', 'Concurrency']]
        p_body = [
            [
                cell(p.get('id')),
                cell(p.get('name')),
                cell(p.get('providerType')),
                cell(f"Spec #{p.get('specialityId') or '--'}"),
                cell(p.get('concurrency') or 'N/A')
            ]
            for p in providers
        ]
        p_table = Table([p_head] + p_body, colWidths=[20*mm, 76*mm, 58*mm, 58*mm, table_width - 212*mm], repeatRows=1)
        p_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
            ('TEXTCOLOR', (0,0), (-1,0), TEAL),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
            ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('FONTSIZE', (0,0), (-1,-1), 9.5),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(p_table)

    # 4. Duration Table
    cal_durs = data.get('calendarPtDurations', {})
    day_names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    elements.append(Paragraph(f"Production Type Duration ({len(pts)})", section_header_style))
    if pts:
        d_head = [header_cell(x) for x in ['ID', 'Production Type', 'Default', 'Calendar', 'Days', 'Templates', 'Validation']]
        d_body = []
        duration_findings = {
            'valid': [],
            'not_in_calendar': [],
            'no_default': [],
            'mixed_duration': [],
            'duration_mismatch': [],
            'multiple_specialties': [],
            'no_specialty': [],
        }
        for pt in pts:
            pt_id = str(pt.get('id'))
            cd = cal_durs.get(pt_id, {})
            cDurs = cd.get('durations', [])
            cDays = [day_names[d] if isinstance(d, int) else d for d in cd.get('days', [])]
            cTmpls = cd.get('templates', [])
            def_mins = pt.get('durationMinutes') or 0
            
            def_str = f"{def_mins} min" if def_mins > 0 else "Not set"
            cal_str = ", ".join([f"{d}min" for d in cDurs]) if cDurs else "Not in calendar"
            days_str = ", ".join(cDays) if cDays else "--"
            tmpls_str = ", ".join(cTmpls) if cTmpls else "--"
            
            pt_name = pt.get('name') or f"Production Type #{pt_id}"
            val_lines = []
            if not cDurs:
                val_lines.append("Coverage gap: not in production calendar")
                duration_findings['not_in_calendar'].append(pt_name)
            elif def_mins == 0:
                val_lines.append("Configuration gap: no default duration")
                duration_findings['no_default'].append(pt_name)
            else:
                valid_durs = [d for d in cDurs if d > 0 and d % def_mins == 0]
                invalid_durs = [d for d in cDurs if d <= 0 or d % def_mins != 0]
                if not invalid_durs:
                    multiples = ", ".join(f"{d // def_mins}x" for d in cDurs)
                    val_lines.append(f"Valid calendar multiples ({multiples})")
                    duration_findings['valid'].append(pt_name)
                elif valid_durs:
                    invalid_str = ", ".join(f"{d} min" for d in invalid_durs)
                    val_lines.append(f"Mixed duration: {invalid_str} not a multiple of {def_mins} min")
                    duration_findings['mixed_duration'].append(pt_name)
                else:
                    cal_str = ", ".join(f"{d} min" for d in cDurs)
                    val_lines.append(f"Mismatch: {cal_str} not a multiple of {def_mins} min")
                    duration_findings['duration_mismatch'].append(pt_name)
            
            spec_count = len(pt.get('providerSpecialities') or [])
            if spec_count > 1:
                val_lines.append(f"Specialty gap: {spec_count} specialties mapped")
                duration_findings['multiple_specialties'].append(pt_name)
            elif spec_count == 0:
                val_lines.append("Specialty gap: no specialty mapped")
                duration_findings['no_specialty'].append(pt_name)
            else:
                val_lines.append("Specialty ok: 1 mapped")
            
            d_body.append([
                cell(pt_id),
                cell(pt_name),
                cell(def_str),
                cell(cal_str, tiny_cell_style),
                cell(days_str, tiny_cell_style),
                cell(tmpls_str, tiny_cell_style),
                cell("; ".join(val_lines), tiny_cell_style)
            ])

        d_table = Table([d_head] + d_body, colWidths=[15*mm, 48*mm, 20*mm, 42*mm, 35*mm, 45*mm, table_width - 205*mm], repeatRows=1)
        d_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
            ('TEXTCOLOR', (0,0), (-1,0), TEAL),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
            ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        elements.append(d_table)

        elements.append(Paragraph("Production Type Duration Inference", section_header_style))
        inference_rows = [[header_cell('Inference'), header_cell('Severity'), header_cell('Affected Production Types'), header_cell('What it means')]]

        def add_duration_finding(title, severity, affected, meaning):
            if affected:
                inference_rows.append([
                    cell(title),
                    severity,
                    cell(_name_list(affected), tiny_cell_style),
                    cell(meaning, tiny_cell_style),
                ])

        add_duration_finding(
            'Calendar coverage gap',
            'High',
            duration_findings['not_in_calendar'],
            'These selected production types are not present in the production calendar data, so no operatory/calendar slot appears configured for them.'
        )
        add_duration_finding(
            'Missing default duration',
            'High',
            duration_findings['no_default'],
            'Calendar slots exist, but the production type default duration is not set, so appointment length cannot be validated.'
        )
        add_duration_finding(
            'Duration mismatch',
            'High',
            duration_findings['duration_mismatch'],
            'Calendar durations are not multiples of the production type default duration, which can create scheduling length mismatches.'
        )
        add_duration_finding(
            'Mixed calendar durations',
            'Medium',
            duration_findings['mixed_duration'],
            'Some calendar durations are valid multiples and some are not; review the templates before enabling this mapping.'
        )
        add_duration_finding(
            'Multiple specialties',
            'Medium',
            duration_findings['multiple_specialties'],
            'These production types map to more than one provider specialty, which can make provider-production matching ambiguous.'
        )
        add_duration_finding(
            'Missing specialty',
            'Medium',
            duration_findings['no_specialty'],
            'These production types have no specialty mapping, so specialty-based provider matching cannot be inferred.'
        )

        if len(inference_rows) == 1:
            inference_rows.append([
                cell('Duration and specialty checks'),
                'Clear',
                cell(_name_list(duration_findings['valid']), tiny_cell_style),
                cell('Every selected production type with calendar data has valid duration multiples and exactly one specialty.', tiny_cell_style)
            ])

        duration_inference_table = Table(inference_rows, colWidths=[45*mm, 25*mm, 92*mm, table_width - 162*mm], repeatRows=1)
        duration_inference_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
            ('TEXTCOLOR', (0,0), (-1,0), TEAL),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
            ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        for row_idx, row in enumerate(inference_rows[1:], 1):
            severity = row[1]
            if severity == 'Clear':
                duration_inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), TEAL)]))
            elif severity == 'High':
                duration_inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), ROSE)]))
            elif severity == 'Medium':
                duration_inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), AMBER)]))
        elements.append(duration_inference_table)

        def format_days(days):
            labels = []
            for day in days or []:
                if isinstance(day, int) and 0 <= day < len(day_names):
                    labels.append(day_names[day])
                    continue
                try:
                    day_idx = int(day)
                except (TypeError, ValueError):
                    labels.append(str(day))
                    continue
                labels.append(day_names[day_idx] if 0 <= day_idx < len(day_names) else str(day))
            return _name_list(labels)

        def format_dates(dates):
            return _name_list([str(date_value)[:10] for date_value in (dates or [])])

        def format_range_when(slot_range):
            days_str = format_days(slot_range.get('days'))
            dates_str = format_dates(slot_range.get('dates'))
            if days_str != "--" and dates_str != "--":
                return f"{days_str}; {dates_str}"
            if days_str != "--":
                return days_str
            return dates_str

        def format_range_locations(slot_range):
            loc_ids = slot_range.get('locationIds') or []
            if not loc_ids:
                op_obj = _get_by_id(op_lookup, slot_range.get('operatory'))
                if op_obj and op_obj.get('locationId') is not None:
                    loc_ids = [op_obj.get('locationId')]
            return _name_list([location_label(lid) for lid in loc_ids])

        slot_rows = [[header_cell(x) for x in ['Production Type', 'Template', 'Day / Date', 'Location', 'Operatory', 'Time', 'Duration']]]
        for pt in pts:
            pt_id = str(pt.get('id'))
            pt_name = pt.get('name') or f"Production Type #{pt_id}"
            cd = cal_durs.get(pt_id, {}) or {}
            for slot_range in cd.get('time_ranges', []) or []:
                duration = slot_range.get('duration')
                duration_str = f"{duration} min" if duration is not None else "--"
                slot_rows.append([
                    cell(pt_name, tiny_cell_style),
                    cell(str(slot_range.get('template') or '--'), tiny_cell_style),
                    cell(format_range_when(slot_range), tiny_cell_style),
                    cell(format_range_locations(slot_range), tiny_cell_style),
                    cell(operatory_label(slot_range.get('operatory')), tiny_cell_style),
                    cell(slot_range.get('time') or '--', tiny_cell_style),
                    cell(duration_str, tiny_cell_style),
                ])

        if len(slot_rows) > 1:
            slot_rows[1:] = sorted(
                slot_rows[1:],
                key=lambda row: (
                    getattr(row[0], 'text', ''),
                    getattr(row[1], 'text', ''),
                    getattr(row[2], 'text', ''),
                    getattr(row[4], 'text', ''),
                    getattr(row[5], 'text', str(row[5])),
                )
            )
            elements.append(Paragraph("Production Calendar Slot Configurations", section_header_style))
            slot_table = Table(
                slot_rows,
                colWidths=[38*mm, 46*mm, 32*mm, 36*mm, 42*mm, 24*mm, table_width - 218*mm],
                repeatRows=1
            )
            slot_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
                ('TEXTCOLOR', (0,0), (-1,0), TEAL),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
                ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
                ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
                ('FONTSIZE', (0,0), (-1,-1), 7.8),
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ]))
            elements.append(slot_table)

    # 5. Operatories
    elements.append(Paragraph("Operatories by Location", section_header_style))
    op_provs = data.get('operatory_providers', {})
    op_pts = data.get('operatory_production_types', {})
    
    loc_groups = {}
    for op in ops:
        lid = op.get('locationId')
        if lid not in loc_groups: loc_groups[lid] = []
        loc_groups[lid].append(op)
    
    for lid, loc_ops in loc_groups.items():
        loc_name = location_label(lid)
        elements.append(Paragraph(f"<b>{escape(loc_name)}</b> ({len(loc_ops)} operatories)", body_style))
        o_head = [header_cell(x) for x in ['Operatory', 'ID', 'Providers', 'Production Types']]
        o_body = []
        for op in sorted(loc_ops, key=lambda x: x.get('sortOrder', 0)):
            op_id = str(op.get('id'))
            pids = _ids_for(op_provs, op_id)
            p_names = [provider_label(pid) for pid in pids]
            
            ptids = _ids_for(op_pts, op_id)
            pt_names = [production_type_label(ptid) for ptid in ptids]
            pt_names = [n for n in pt_names if n.lower() != 'lunch']

            o_body.append([
                cell(op.get('name')),
                cell(op_id),
                cell(_limited_name_list(p_names, limit=18), tiny_cell_style),
                cell(_limited_name_list(pt_names, limit=18), tiny_cell_style)
            ])
        
        o_table = Table([o_head] + o_body, colWidths=[40*mm, 20*mm, 96*mm, table_width - 156*mm], repeatRows=1)
        o_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
            ('TEXTCOLOR', (0,0), (-1,0), TEAL),
            ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
            ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ]))
        elements.append(o_table)
        elements.append(Spacer(1, 5*mm))

    # 6. Operatory Coverage Inference
    elements.append(Paragraph("Operatory Coverage Inference", section_header_style))
    selected_provider_ids = {_id_key(p.get('id')) for p in providers if p.get('id') is not None}
    selected_pt_ids = {_id_key(pt.get('id')) for pt in pts if pt.get('id') is not None}
    provider_ids_in_operatories = set()
    pt_ids_in_operatories = set()

    for op in ops:
        op_id = op.get('id')
        for pid in _ids_for(op_provs, op_id):
            key = _id_key(pid)
            if key in selected_provider_ids:
                provider_ids_in_operatories.add(key)
        for ptid in _ids_for(op_pts, op_id):
            key = _id_key(ptid)
            if key in selected_pt_ids:
                pt_ids_in_operatories.add(key)

    missing_provider_ids = sorted(selected_provider_ids - provider_ids_in_operatories)
    missing_pt_ids = sorted(selected_pt_ids - pt_ids_in_operatories)

    inference_rows = [[header_cell('Check'), header_cell('Result'), header_cell('Details')]]
    if selected_pt_ids:
        if missing_pt_ids:
            missing_names = [production_type_label(ptid) for ptid in missing_pt_ids]
            inference_rows.append([
                cell('Production Types'),
                'Coverage gap',
                cell(f"{len(missing_names)} selected production type(s) are not assigned to any operatory: {_name_list(missing_names)}")
            ])
        else:
            inference_rows.append([
                cell('Production Types'),
                'Covered',
                cell('Every selected production type is assigned to at least one operatory.')
            ])
    else:
        inference_rows.append([
            cell('Production Types'),
            'No selection',
            cell('No production types were selected for validation.')
        ])

    if selected_provider_ids:
        if missing_provider_ids:
            missing_names = [provider_label(pid) for pid in missing_provider_ids]
            inference_rows.append([
                cell('Providers'),
                'Coverage gap',
                cell(f"{len(missing_names)} selected provider(s) are not assigned to any operatory: {_name_list(missing_names)}")
            ])
        else:
            inference_rows.append([
                cell('Providers'),
                'Covered',
                cell('Every selected provider is assigned to at least one operatory.')
            ])
    else:
        inference_rows.append([
            cell('Providers'),
            'No selection',
            cell('No providers were selected for validation.')
        ])

    inference_table = Table(inference_rows, colWidths=[45*mm, 35*mm, table_width - 80*mm], repeatRows=1)
    inference_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
        ('TEXTCOLOR', (0,0), (-1,0), TEAL),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
        ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    for row_idx, row in enumerate(inference_rows[1:], 1):
        result = row[1]
        if result == 'Covered':
            inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), TEAL)]))
        elif result == 'Coverage gap':
            inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), AMBER)]))
    elements.append(inference_table)

    # 7. Specialty Matrix
    if providers and pts:
        elements.append(Paragraph("Provider x Production Type - Specialty Match", section_header_style))
        pt_codes = {
            _id_key(pt.get('id')): f"PT{idx + 1}"
            for idx, pt in enumerate(pts)
        }
        m_rows = []
        provider_match_counts = {}
        pt_match_counts = {_id_key(pt.get('id')): 0 for pt in pts}
        providers_missing_spec = []
        pts_missing_spec = []
        mismatch_pairs = []

        for pt in pts:
            if not (pt.get('providerSpecialities') or []):
                pts_missing_spec.append(pt.get('name') or f"Production Type #{pt.get('id')}")

        for prov in providers:
            prov_spec = prov.get('specialityId')
            prov_name = prov.get('name') or f"Provider #{prov.get('id')}"
            provider_key = _id_key(prov.get('id'))
            provider_match_counts[provider_key] = 0
            if not prov_spec:
                providers_missing_spec.append(prov_name)
            row_values = []
            for pt in pts:
                pt_key = _id_key(pt.get('id'))
                pt_name = pt.get('name') or f"Production Type #{pt.get('id')}"
                pt_specs = pt.get('providerSpecialities') or []
                if not prov_spec or not pt_specs:
                    row_values.append("-")
                elif prov_spec in pt_specs:
                    provider_match_counts[provider_key] += 1
                    pt_match_counts[pt_key] += 1
                    row_values.append("Y")
                else:
                    mismatch_pairs.append(
                        f"{prov_name} -> {pt_name} (provider spec {prov_spec}; PT specs {', '.join(map(str, pt_specs))})"
                    )
                    row_values.append("N")
            m_rows.append({'provider_name': prov_name, 'values': row_values})
        
        code_rows = [[header_cell('Code'), header_cell('Production Type')]]
        for pt in pts:
            pt_key = _id_key(pt.get('id'))
            code_rows.append([
                cell(pt_codes[pt_key], tiny_cell_style),
                cell(pt.get('name') or f"Production Type #{pt.get('id')}", tiny_cell_style)
            ])

        code_table = Table(code_rows, colWidths=[22*mm, table_width - 22*mm], repeatRows=1)
        code_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
            ('TEXTCOLOR', (0,0), (-1,0), TEAL),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
            ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('FONTSIZE', (0,0), (-1,-1), 7.5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        elements.append(Paragraph("Production Type Codes", body_style))
        elements.append(code_table)
        elements.append(Spacer(1, 4*mm))

        max_pt_cols = 18
        provider_col_width = 55*mm
        for start_idx in range(0, len(pts), max_pt_cols):
            chunk = pts[start_idx:start_idx + max_pt_cols]
            end_idx = start_idx + len(chunk)
            chunk_codes = [pt_codes[_id_key(pt.get('id'))] for pt in chunk]
            m_head = [header_cell('Provider')] + [header_cell(code) for code in chunk_codes]
            m_body = [
                [cell(row['provider_name'], tiny_cell_style)] + row['values'][start_idx:end_idx]
                for row in m_rows
            ]
            pt_col_width = (table_width - provider_col_width) / max(len(chunk), 1)
            m_table = Table(
                [m_head] + m_body,
                colWidths=[provider_col_width] + [pt_col_width for _ in chunk],
                repeatRows=1
            )
            m_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
                ('TEXTCOLOR', (0,0), (-1,0), TEAL),
                ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
                ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
                ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
                ('FONTSIZE', (0,0), (-1,-1), 7.2),
                ('ALIGN', (1,1), (-1,-1), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            for r_idx, row in enumerate(m_body):
                for c_idx, val in enumerate(row[1:], 1):
                    if val == 'Y':
                        m_table.setStyle(TableStyle([('TEXTCOLOR', (c_idx, r_idx+1), (c_idx, r_idx+1), TEAL)]))
                    elif val == 'N':
                        m_table.setStyle(TableStyle([('TEXTCOLOR', (c_idx, r_idx+1), (c_idx, r_idx+1), ROSE)]))

            if len(pts) > max_pt_cols:
                elements.append(Paragraph(f"Specialty Matrix Columns {chunk_codes[0]} to {chunk_codes[-1]}", body_style))
            elements.append(m_table)
            elements.append(Spacer(1, 4*mm))

        elements.append(Paragraph("Specialty Match Inference", section_header_style))
        matrix_inference_rows = [[header_cell('Inference'), header_cell('Severity'), header_cell('Affected'), header_cell('What it means')]]

        providers_without_matches = [
            prov.get('name') or f"Provider #{prov.get('id')}"
            for prov in providers
            if provider_match_counts.get(_id_key(prov.get('id')), 0) == 0
        ]
        pts_without_matches = [
            pt.get('name') or f"Production Type #{pt.get('id')}"
            for pt in pts
            if pt_match_counts.get(_id_key(pt.get('id')), 0) == 0
        ]

        def add_matrix_finding(title, severity, affected, meaning):
            if affected:
                matrix_inference_rows.append([
                    cell(title),
                    severity,
                    cell(_limited_name_list(affected), tiny_cell_style),
                    cell(meaning, tiny_cell_style),
                ])

        add_matrix_finding(
            'Missing provider specialty',
            'High',
            providers_missing_spec,
            'These providers do not have a specialty ID, so specialty-based production type matching cannot be inferred for them.'
        )
        add_matrix_finding(
            'Missing production type specialty',
            'High',
            pts_missing_spec,
            'These production types do not list provider specialties, so no provider can be confidently matched to them by specialty.'
        )
        add_matrix_finding(
            'Provider has no compatible production type',
            'High',
            providers_without_matches,
            'These selected providers have zero specialty matches among the selected production types.'
        )
        add_matrix_finding(
            'Production type has no compatible provider',
            'High',
            pts_without_matches,
            'These selected production types have zero compatible selected providers by specialty.'
        )
        add_matrix_finding(
            'Specialty mismatch pairs',
            'Medium',
            mismatch_pairs,
            'These provider-production type combinations have specialty data on both sides, but the provider specialty is not allowed by the production type.'
        )

        if len(matrix_inference_rows) == 1:
            match_count = sum(provider_match_counts.values())
            matrix_inference_rows.append([
                cell('Specialty matching'),
                'Clear',
                cell(f'{match_count} compatible provider-production type pair(s)', tiny_cell_style),
                cell('Every selected provider has at least one compatible production type, and every selected production type has at least one compatible provider.', tiny_cell_style)
            ])

        matrix_inference_table = Table(matrix_inference_rows, colWidths=[50*mm, 25*mm, 90*mm, table_width - 165*mm], repeatRows=1)
        matrix_inference_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), HEADER_BG),
            ('TEXTCOLOR', (0,0), (-1,0), TEAL),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,1), (-1,-1), CARD_BG),
            ('TEXTCOLOR', (0,1), (-1,-1), TEXT_COLOR),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ]))
        for row_idx, row in enumerate(matrix_inference_rows[1:], 1):
            severity = row[1]
            if severity == 'Clear':
                matrix_inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), TEAL)]))
            elif severity == 'High':
                matrix_inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), ROSE)]))
            elif severity == 'Medium':
                matrix_inference_table.setStyle(TableStyle([('TEXTCOLOR', (1, row_idx), (1, row_idx), AMBER)]))
        elements.append(matrix_inference_table)

    doc.build(elements, onFirstPage=add_page_background, onLaterPages=add_page_background)
    buffer.seek(0)
    return buffer
