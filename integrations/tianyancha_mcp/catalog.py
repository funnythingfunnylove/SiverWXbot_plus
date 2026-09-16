"""Website section labels observed on Tianyancha company navigation (2026-09-16).

A registered adapter is not proof of account access, records, or successful coverage.
Paths are restricted to company-page categories; no official API is used.
"""
GROUPS = {
    'basic': ('', '基本信息', '''工商信息|股东信息|主要人员|对外投资|控制企业|变更记录|分支机构|财务数据|企业年报|企业公示|最终受益人|实际控制人|协同股东|疑似关系|同行分析'''),
    'legal': ('sifa', '法律诉讼', '''司法案件|涉诉关系|开庭公告|裁判文书|法院公告|限制消费令|限制出境|终本案件|失信被执行人|被执行人|股权冻结|送达公告|立案信息|破产案件|司法拍卖|询价评估|财产悬赏公告|诉前调解'''),
    'risk': ('jingxian', '经营风险', '''注销备案|简易注销|清算信息|惩戒名单|严重违法|行政处罚|环保处罚|税收违法|税务非正常户|欠税公告|违规处理|经营异常|政府约谈|产品召回|土地抵押|股权出质|股权质押|对外担保|担保风险|动产抵押|劳动仲裁|公示催告'''),
    'business': ('jingzhuang', '经营信息', '''招投标|招聘信息|新闻舆情|行政许可|税务评级|纳税人资质|信用评级|抽查检查|双随机抽查|经营商品|资质证书|政府公告|公告研报|资产交易|地块公示|土地转让|进出口信用|债券信息|购地信息|电信许可|供应商|客户|上榜榜单|食品安全'''),
    'development': ('gongsi', '公司发展', '''融资历程|核心团队|企业业务|投资事件|荣誉|竞品信息|投资机构|科创分'''),
    'intellectual_property': ('zhishi', '知识产权', '''商标信息|商标文书|专利信息|集成电路布图|软件著作权|作品著作权|网络服务备案|标准信息|APP|微信公众号|微博|抖音/快手|商业特许经营|知识产权出质'''),
    'history': ('past', '历史信息', '''历史工商信息|历史法定代表人|历史股东信息|股权变更历程|历史主要人员|高管变更历程|历史对外投资|历史开庭公告|历史裁判文书|历史法院公告|历史失信被执行人|历史被执行人|历史限制消费令|历史知识产权出质|历史终本案件|历史股权冻结|历史送达公告|历史立案信息|历史诉前调解|历史破产案件|历史经营异常|历史行政处罚|历史严重违法|历史环保处罚|历史股权出质|历史动产抵押|历史欠税公告|历史土地抵押|历史行政许可|历史荣誉|历史商标信息|历史专利信息|历史备案网站'''),
}
SECTIONS = {label: {'group': group, 'path': path}
            for group, (path, _, labels) in GROUPS.items() for label in labels.split('|')}
# Discoverable convenience tools, with the same extraction/coverage contract as the generic tool.
TOOLS = {
    'get_company_shareholders': '股东信息',
    'get_company_people': '主要人员',
    'get_company_investments': '对外投资',
    'get_company_controlled_entities': '控制企业',
    'get_company_actual_controller': '实际控制人',
    'get_company_beneficial_owners': '最终受益人',
    'get_company_relationships': '疑似关系',
    'get_company_changes': '变更记录',
    'get_company_legal_cases': '司法案件',
    'get_company_hearings': '开庭公告',
    'get_company_judgments': '裁判文书',
    'get_company_enforcements': '被执行人',
    'get_company_dishonest_enforcements': '失信被执行人',
    'get_company_consumption_restrictions': '限制消费令',
    'get_company_final_enforcement_cases': '终本案件',
    'get_company_equity_freezes': '股权冻结',
    'get_company_administrative_penalties': '行政处罚',
    'get_company_abnormal_operations': '经营异常',
    'get_company_tax_arrears': '欠税公告',
    'get_company_guarantees': '对外担保',
    'get_company_equity_pledges': '股权出质',
    'get_company_mortgages': '动产抵押',
    'get_company_bonds': '债券信息',
    'get_company_financials': '财务数据',
    'get_company_annual_reports': '企业年报',
    'get_company_licenses': '行政许可',
    'get_company_qualifications': '资质证书',
    'get_company_bids': '招投标',
    'get_company_news': '新闻舆情',
    'get_company_suppliers': '供应商',
    'get_company_customers': '客户',
}


def company_url(company_id, group='basic'):
    suffix = GROUPS[group][0]
    return f'https://www.tianyancha.com/company/{company_id}' + (f'/{suffix}' if suffix else '')

# Read-only tabs observed inside supported sections. No arbitrary click targets.
VIEWS = {
    '股东信息': ['股东信息', '历史股东信息', '股权变更历程'],
    '主要人员': ['主要人员', '历史主要人员', '高管变更历程'],
    '对外投资': ['对外投资', '对外投资(间接)', '历史对外投资'],
    '最终受益人': ['受益自然人', '受益机构'],
    '股权出质': ['全部', '身为质权人', '身为出质人', '身为股权标的企业'],
}
