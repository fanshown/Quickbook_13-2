# -*- coding: utf-8 -*-
#################################################################################
# Author      : Webkul Software Pvt. Ltd. (<https://webkul.com/>)
# Copyright(c): 2015-Present Webkul Software Pvt. Ltd.
# License URL : https://store.webkul.com/license.html/
# All Rights Reserved.
#
#
#
# This program is copyright property of the author mentioned above.
# You can`t redistribute it and/or modify it.
#
#
# You should have received a copy of the License along with this program.
# If not, see <https://store.webkul.com/license.html/>
#################################################################################

from odoo import models,fields,api,_
from odoo.exceptions import UserError,ValidationError,RedirectWarning
from datetime import date,datetime,timedelta
import dateutil
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT, float_is_zero
import pytz, time, math
from dateutil.relativedelta import relativedelta
from odoo.addons import decimal_precision as dp
import logging
_logger = logging.getLogger(__name__)

class PathoTestRequest(models.Model):
    _name = "patho.testrequest"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'id desc, test_date desc'
    _description = "Pathology Test Request"

    @api.depends('patho_line_ids.price_total')
    def compute_amount(self):
        for rec in self:
            amount_untaxed = amount_tax = 0.0
            for line in rec.patho_line_ids:
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            rec.update({
                'amount_untaxed': rec.pricelist_id.currency_id.round(amount_untaxed),
                'amount_tax': rec.pricelist_id.currency_id.round(amount_tax),
                'amount_total': amount_untaxed + amount_tax,
            })

    @api.model
    def set_patho_source(self):
        source = self.env.ref('wk_pathology_management.patho_source1')
        return source

    name = fields.Char(string = "Number", default="New", copy=False)
    customer_id = fields.Many2one("res.partner", "Customer", required=True)
    test_date = fields.Date(string="Test Date", required=True, default=fields.Date.today(), copy=False)
    status = fields.Selection([('new','New'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('inprocess', 'In Process'),
        ('rejected', 'Rejected'),
        ('done', 'Done')], string = "Status", default = "new", track_visibility="onchange", copy=False)
    test_day = fields.Char("Day", compute="compute_testday")
    # invoice_id = fields.Many2one('account.invoice', 'Invoice', track_visibility="onchange")
    invoice_count = fields.Integer(string='# of Invoices',  readonly=True, compute= "compute_invoice_count")
    invoice_ids = fields.Many2many("account.invoice", string='Invoices',  readonly=True, copy=False)
    invoice_status = fields.Selection([
        ('upselling', 'Upselling Opportunity'),
        ('invoiced', 'Fully Invoiced'),
        ('to invoice', 'To Invoice'),
        ('no', 'Nothing to Invoice')
        ], string='Invoice Status', compute="_get_invoice_status", store=True, readonly=True, copy=False)

    inv_state = fields.Char(string="Invoice State", compute="compute_inv_state")
    source = fields.Many2one('patho.source', string="Source", default=set_patho_source)
    currency_id = fields.Many2one("res.currency" , string="Currency",
        related="pricelist_id.currency_id")
    pricelist_id = fields.Many2one("product.pricelist", string="Pricelist",
        related= "customer_id.property_product_pricelist")
    enable_notify_reminder = fields.Boolean(string="Notify using Mail", default= lambda self: self.env['ir.default'].sudo().get('patho.config.settings', 'enable_notify_reminder'))
    # remind_in = fields.Selection([('days', 'Day(s)'),('hours', 'Hour(s)')], string="Remind In", default="hours")
    remind_time = fields.Integer(string="Reminder Time", default=1)
    ref_by = fields.Char("Referred By")
    description = fields.Text("Description")
    amount_untaxed = fields.Float(compute="compute_amount", string='Untaxed Amount', store=True, readonly=True, track_visibility='onchange')
    amount_tax = fields.Float(compute="compute_amount" , string='Taxes', store=True, readonly=True, )
    amount_total = fields.Float( compute="compute_amount", string='Total', store=True, readonly=True, track_visibility='onchange')
    is_mail_sent = fields.Boolean("Reminder Mail Send", copy=False)
    patho_line_ids = fields.One2many('patho.testrequest.lines', 'testreq_id', string='Test Request Lines', copy=True, auto_join=True )
    color = fields.Integer("Color")
    notify_customer_on_approve_testreq = fields.Boolean('Notify Customer on New Test Request',
                default=lambda self: self.env['ir.default'].get("patho.config.settings", 'enable_notify_customer_on_approve_testreq')
                       )
    report_collection_date = fields.Date('Report Collection Date', copy=False)
    patho_test_report_ids = fields.One2many('patho.testreport', 'testreq_id', string="Pathology Test Report", copy=False)
    sale_order_id = fields.Many2one('sale.order', "Sale Order", copy=False)
    lab_center_id = fields.Many2one('patho.lab.centers','Laboratory Center', domain="[('is_lab_center','=', True)]",
        default = lambda self: self.env.user.partner_id.lab_center_id.id if self.env.user.partner_id.lab_center_id else self.env['ir.default'].get("patho.config.settings", 'lab_center_id'))
    collection_center_id = fields.Many2one('patho.lab.centers', 'Collection Center',
        domain="[('is_collection_center','=', True)]",
        default = lambda self: self.env.user.partner_id.collection_center_id.id if self.env.user.partner_id.collection_center_id else self.env['ir.default'].get("patho.config.settings", 'collection_center_id'))

    @api.onchange('collection_center_id')
    def compute_lab_center(self):
        if self.collection_center_id:
            self.lab_center_id = self.collection_center_id.primary_labcenter_id.id

    @api.multi
    def compute_inv_state(self):
        for rec in self:
            if rec.invoice_count != 0:
                if rec.sale_order_id:
                    if any(inv.state == 'draft' for inv in rec.invoice_ids):
                        rec.inv_state = 'draft'
                    if any(inv.state == 'open' for inv in rec.invoice_ids):
                        rec.inv_state = 'open'
                    if all(inv.state == 'paid' for inv in rec.invoice_ids):
                        rec.inv_state = 'paid'
                    if any(inv.state == 'cancel' for inv in rec.invoice_ids):
                        rec.inv_state = 'cancelled'
                else:
                    rec.inv_state = rec.invoice_ids[0].state

    @api.multi
    def compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(set(rec.invoice_ids.ids))
        return


    @api.multi
    def create_patho_testreport_records(self):
        for rec in self.patho_line_ids:
            if rec.product_id.is_test:
                values = {
                    'labtest'           : rec.product_id.id,
                    'diagnosis_states'  : 'draft',
                    'testreq_id'        : self.id,
                    'comment'           : '',
                }
                self.env['patho.testreport'].create(values)
            if rec.product_id.is_test_package:
                for test in rec.product_id.product_tmpl_ids:
                    values = {
                        'labtest'           : test.product_variant_id.id,
                        'diagnosis_states'  : 'draft',
                        'testreq_id'        : self.id,
                        'comment'           : '',
                    }
                    self.env['patho.testreport'].create(values)
        return True

    @api.multi
    def button_approve_request(self):
        for rec in self:
            if not rec.patho_line_ids:
                raise UserError(_("No Labtest Added, please add atleast one Labtest."))
            rec.create_patho_testreport_records()
            rec.write({'status' : 'approved'})
            rec.send_approve_testreq_mail()
        return True


    @api.depends('test_date')
    def compute_testday(self):
        for rec in self:
            if rec.test_date:
                rec.test_day = datetime.strptime(str(rec.test_date) ,'%Y-%m-%d').date().strftime('%A')
        return True

    @api.onchange('test_date')
    def compute_testdate(self):
        test_date = self.test_date
        if test_date:
            dt = test_date
            d1 = datetime.strptime(str(dt),"%Y-%m-%d").date()
            d2 = date.today()
            rd = relativedelta(d2,d1)
            if rd.days > 0 or rd.months > 0 or rd.years > 0:
                raise UserError(_("Test Date Should be after Today"))

    def send_approve_testreq_mail(self):
        if self.notify_customer_on_approve_testreq == True:
            template_id = self.env.ref("wk_pathology_management.patho_mgmt_email_template_to_customer") or False
            if template_id:
                template_id.send_mail(self.id,force_send=True)

    @api.multi
    def button_set_to_pending(self):
        self.write({'status' : 'pending'})
        return True

    @api.multi
    def button_set_to_new_request(self):
        self.write({'status' : 'new'})
        return True

    @api.multi
    def button_view_sale_order(self):
        action = self.env.ref('sale.action_orders').read()[0]
        action['domain'] = [('id', '=', self.sale_order_id.id)]
        return action

    @api.multi
    def button_send_by_mail(self):
        self.ensure_one()

        ir_model_data = self.env['ir.model.data']
        try:
            template_id = ir_model_data.get_object_reference('wk_pathology_management', 'patho_send_report_by_email_to_customer')[1]
        except ValueError:
            template_id = False

        try:
            compose_form_id = ir_model_data.get_object_reference('mail', 'email_compose_message_wizard_form')[1]
        except ValueError:
            compose_form_id = False
        ctx = {
            'default_model': 'patho.testrequest',
            'default_res_id': self.ids[0],
            'default_use_template': bool(template_id),
            'default_template_id': template_id,
            'default_composition_mode': 'comment',
            'mark_so_as_sent': True,
            # 'custom_layout': "wk_pathology_management.mail_template_data_notification_email_sale_order",
            'proforma': self.env.context.get('proforma', False),
            'force_email': True
        }
        return {
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form_id, 'form')],
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
        }

    @api.multi
    def button_print_report(self):
        return self.env.ref('wk_pathology_management.patho_mgmt_patient_report').report_action(self)


    @api.multi
    def testreq_prepare_invoice(self):
        self.ensure_one()
        journal_id = self.env['account.invoice'].default_get(['journal_id'])['journal_id']
        if not journal_id:
            raise UserError(_('Please define an accounting sales journal for this company.'))
        invoice_vals = {
            'origin': self.name,
            'type': 'out_invoice',
            'account_id': self.customer_id.property_account_receivable_id.id,
            'partner_id': self.customer_id.id,
            'partner_shipping_id': self.customer_id.id,
            'journal_id': journal_id,
            'currency_id': self.pricelist_id.currency_id.id,
            'comment': self.description,
            'payment_term_id': self.customer_id.property_payment_term_id.id,
            'fiscal_position_id': self.customer_id.property_account_position_id.id,
            'company_id': self.customer_id.company_id.id,
        }
        return invoice_vals



    @api.multi
    def button_create_invoice(self):
        if not self.patho_line_ids:
            raise UserError(_("There are no invoicable lines."))

        company_id = self.customer_id.company_id.id
        p = self.customer_id if not company_id else self.customer_id.with_context(force_company=company_id)
        # type = self.type
        if p:
            rec_account = p.property_account_receivable_id
            pay_account = p.property_account_payable_id
            if not rec_account and not pay_account:
                action = self.env.ref('account.action_account_config')
                msg = _('Cannot find a chart of accounts for this company, You should configure it. \nPlease go to Account Configuration.')
                raise RedirectWarning(msg, action.id, _('Go to the configuration panel'))

            # if type in ('out_invoice', 'out_refund'):
            account_id = rec_account.id
            payment_term_id = p.property_payment_term_id.id

        for rec in self:
            invoice_vals = {
                # 'name': self.client_order_ref or '',
                'origin': rec.name,
                'type': 'out_invoice',
                'account_id': account_id,
                'partner_id': rec.customer_id.id,
                'partner_shipping_id': self.customer_id.id,
                # 'journal_id': journal_id,
                'currency_id': rec.pricelist_id.currency_id.id,
                'comment': rec.description,
                'payment_term_id': payment_term_id,
                'fiscal_position_id': self.customer_id.property_account_position_id.id,
                'company_id': self.customer_id.company_id.id,
                # 'user_id': self.user_id and self.user_id.id,
                # 'team_id': self.team_id.id
            }
            invoice_obj = self.env['account.invoice'].create(invoice_vals)
            self.write({'invoice_ids': [(6, 0, [invoice_obj.id])]})
            for line in rec.patho_line_ids:
                line.testreq_invoice_line_create(invoice_obj.id)
            invoice_obj.compute_taxes()
            return self.button_view_invoice()


    @api.multi
    def button_reject_request(self):
        view_id= self.env["testreq.rejectreason.wizard"]
        vals= {
            'name'  :  _("Mention reason to reject Test Request"),
            'view_mode' : 'form',
            'view_type' : 'form',
            'res_model' : 'testreq.rejectreason.wizard',
            'res_id'    : view_id.id,
            'type'  : "ir.actions.act_window",
            'target'    : 'new',
        }
        return vals


    @api.model
    def create(self,vals):
        vals['name'] = self.env['ir.sequence'].sudo().next_by_code("patho.testrequest")
        testreq = super(PathoTestRequest,self).create(vals)
        testreq.compute_testdate()
        self.write({'status' : 'pending'})
        return testreq

    @api.multi
    def write(self, vals):
        if vals.get("status"):
            for rec in self:
                if rec.status == 'new' and vals.get("status") == 'done' :
                    raise UserError(_('Invalid Move !!'))
                # if rec.status == 'new' and vals.get("status") == 'approved' :
                #     raise UserError(_('Invalid Move !!'))
                if rec.status == 'pending' and vals.get("status") == 'new' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'pending' and vals.get("status") == 'done' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'approved' and vals.get("status") == 'new' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'approved' and vals.get("status") == 'pending' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'rejected' and vals.get("status") == 'inprocess' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'rejected' and vals.get("status") == 'pending' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'rejected' and vals.get("status") == 'approved' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'rejected' and vals.get("status") == 'done' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'done' and vals.get("status") == 'new' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'done' and vals.get("status") == 'pending' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'done' and vals.get("status") == 'approved' :
                    raise UserError(_('Invalid Move !!'))
                if rec.status == 'done' and vals.get("status") == 'rejected' :
                    raise UserError(_('Invalid Move !!'))
        res = super(PathoTestRequest, self).write(vals)
        if vals.get("test_date"):
            self.compute_testdate()
        return res

    @api.multi
    def button_view_invoice(self):
        invoices = self.mapped('invoice_ids')
        action = self.env.ref('account.action_invoice_tree1').read()[0]
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            action['views'] = [(self.env.ref('account.invoice_form').id, 'form')]
            action['res_id'] = invoices.ids[0]
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action

    @api.one
    def send_reminder_mail_to_customer(self):
        template_obj = self.env['mail.template']
        patho_config_obj = self.env['patho.config.settings'].get_values()
        if patho_config_obj["enable_notify_reminder"] and patho_config_obj.get("notify_reminder_mail_template") and patho_config_obj["notify_reminder_mail_template"]:
            temp_id = patho_config_obj[
                "notify_reminder_mail_template"]
            if temp_id:
                template_obj.browse(temp_id).send_mail(self.id, force_send=True)
        return True

    @api.model
    def patho_send_mail_for_reminder_scheduler_queue(self):
        obj = self.search([])
        for rec in obj:
            if rec.status == 'approved':
                if rec.enable_notify_reminder:
                    remind_time = rec.remind_time
                    if remind_time:
                        current_time = date.today()
                        later_time = datetime.strptime(str(rec.test_date),"%Y-%m-%d").date() - timedelta(days=remind_time)
                        time_diff = relativedelta(later_time, current_time)
                        if time_diff.days ==  0 and time_diff.months == 0 and time_diff.years == 0:
                            if not rec.is_mail_sent:
                                self.send_reminder_mail_to_customer()
                                rec.is_mail_sent == True

class PathoTestRequestLines(models.Model):
    _name = 'patho.testrequest.lines'
    _description = "Pathology TestRequest Lines"

    @api.multi
    def patho_test_only_show_package(self):
        return True
    @api.depends('status', 'product_qty', 'qty_to_invoice', 'qty_invoiced')
    def _compute_invoice_status(self):
        """
        Compute the invoice status of a SO line. Possible statuses:
        - no: if the SO is not in status 'sale' or 'done', we consider that there is nothing to
          invoice. This is also hte default value if the conditions of no other status is met.
        - to invoice: we refer to the quantity to invoice of the line. Refer to method
          `_get_to_invoice_qty()` for more information on how this quantity is calculated.
        - upselling: this is possible only for a product invoiced on ordered quantities for which
          we delivered more than expected. The could arise if, for example, a project took more
          time than expected but we decided not to invoice the extra cost to the client. This
          occurs onyl in state 'sale', so that when a SO is set to done, the upselling opportunity
          is removed from the list.
        - invoiced: the quantity invoiced is larger or equal to the quantity ordered.
        """
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for line in self:
            if line.status not in ('approved', 'inprocess', 'done'):
                line.invoice_status = 'no'
            elif not float_is_zero(line.qty_to_invoice, precision_digits=precision):
                line.invoice_status = 'to invoice'
            elif line.status == 'approved' and line.product_id.invoice_policy == 'order':
                    # float_compare(line.qty_delivered, line.product_uom_qty, precision_digits=precision) == 1:
                line.invoice_status = 'upselling'
            elif float_compare(line.qty_invoiced, line.product_qty, precision_digits=precision) >= 0:
                line.invoice_status = 'invoiced'
            else:
                line.invoice_status = 'no'

    @api.depends('invoice_lines.invoice_id.state', 'invoice_lines.quantity')
    def _get_invoice_qty(self):
        """
        Compute the quantity invoiced. If case of a refund, the quantity invoiced is decreased. Note
        that this is the case only if the refund is generated from the SO and that is intentional: if
        a refund made would automatically decrease the invoiced quantity, then there is a risk of reinvoicing
        it automatically, which may not be wanted at all. That's why the refund has to be created from the SO
        """
        for line in self:
            qty_invoiced = 0.0
            for invoice_line in line.invoice_lines:
                if invoice_line.invoice_id.state != 'cancel':
                    if invoice_line.invoice_id.type == 'out_invoice':
                        qty_invoiced += invoice_line.uom_id._compute_quantity(invoice_line.quantity, line.product_uom)
                    elif invoice_line.invoice_id.type == 'out_refund':
                        qty_invoiced -= invoice_line.uom_id._compute_quantity(invoice_line.quantity, line.product_uom)
            line.qty_invoiced = qty_invoiced




    @api.depends('qty_invoiced', 'product_qty', 'testreq_id.status')
    def _get_to_invoice_qty(self):
        """
        Compute the quantity to invoice. If the invoice policy is order, the quantity to invoice is
        calculated from the ordered quantity. Otherwise, the quantity delivered is used.
        """
        for line in self:
            if line.testreq_id.status in ['approved','inprocess' , 'done']:
                if line.product_id.invoice_policy == 'order':
                    line.qty_to_invoice = line.product_qty - line.qty_invoiced
                # else:
                #     line.qty_to_invoice = line.qty_delivered - line.qty_invoiced
            else:
                line.qty_to_invoice = 0

    @api.depends('product_qty', 'discount', 'price_unit', 'tax_id')
    def compute_line_total(self):
        """
        Compute the amounts of the Test Requests line.
        """
        for line in self:
            # price = line.price_unit
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.tax_id.compute_all(price, line.testreq_id.currency_id, line.product_qty, product=line.product_id, partner=line.testreq_id.customer_id)
            line.update({
                'price_tax': sum(t.get('amount', 0.0) for t in taxes.get('taxes', [])),
                'price_total': taxes['total_included'],
                'price_subtotal': taxes['total_excluded'],
            })

    status = fields.Selection([
        ('new','New'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('inprocess', 'In Process'),
        ('rejected', 'Rejected'),
        ('done', 'Done')
    ], related='testreq_id.status', string='Test Request Status', readonly=True, copy=False, store=True, default='new')

    testreq_id = fields.Many2one('patho.testrequest', string="Test Request Reference",required=True ,
        ondelete ='cascade', index=True, copy=False)
    name = fields.Text(string='Description', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    product_qty = fields.Float(string='Quantity', digits=dp.get_precision('Product Unit of Measure'),
        required=True, default=1.0)
    tax_id = fields.Many2many('account.tax', string='Tax')
    price_unit = fields.Float('Unit Price', required=True, digits=dp.get_precision('Product Price'), default=0.0)
    discount = fields.Float(string='Discount (%)', digits=dp.get_precision('Discount'), default=0.0)
    price_subtotal = fields.Float(compute='compute_line_total', string='Subtotal', readonly=True, store=True)
    price_tax = fields.Float(compute='compute_line_total', string='Taxes', readonly=True, store=True)
    price_total = fields.Float(compute='compute_line_total', string='Total', readonly=True, store=True)
    is_test_package = fields.Boolean("Is Test Package", related="product_id.is_test_package")

    invoice_lines = fields.Many2many('account.invoice.line', 'testreq_line_invoice_rel', 'patho_line_id', 'invoice_line_id', string='Invoice Lines', copy=False)
    invoice_status = fields.Selection([
        ('upselling', 'Upselling Opportunity'),
        ('invoiced', 'Fully Invoiced'),
        ('to invoice', 'To Invoice'),
        ('no', 'Nothing to Invoice')
        ], string='Invoice Status', compute='_compute_invoice_status', store=True, readonly=True, default='no')
    qty_to_invoice = fields.Float(
        compute='_get_to_invoice_qty', string='To Invoice', store=True, readonly=True,
        digits=dp.get_precision('Product Unit of Measure'))
    qty_invoiced = fields.Float(
        compute='_get_invoice_qty', string='Invoiced', store=True, readonly=True,
        digits=dp.get_precision('Product Unit of Measure'))
    # amt_to_invoice = fields.Monetary(string='Amount To Invoice', compute='_compute_invoice_amount', store=True)
    # amt_invoiced = fields.Monetary(string='Amount Invoiced', compute='_compute_invoice_amount', store=True)
    sale_order_line_id = fields.Many2one('sale.order.line',"Sale Order Line Ref")

    @api.multi
    @api.onchange('product_id')
    def compute_testreq_products(self):
        self.name = self.product_id.name
        domain = { 'product_id' : ['|', ('is_test', '=', True), ('is_test_package','=',True)]}
        return {'domain': domain}

    @api.multi
    @api.onchange('product_id')
    def product_id_change(self):
        vals = {}
        if self.product_id:
            product = self.product_id
            name = product.name_get()[0][1]
            if product.description_sale:
                name += '\n' + product.description_sale
                vals['name'] = name
            if product.taxes_id:
                vals['tax_id'] = product.taxes_id
            vals['price_unit'] = self.product_id.lst_price
        self.update(vals)

    @api.multi
    def prepare_testreq_invoice_line(self):
        """
        Prepare the dict of values to create the new invoice line for a testrequest line.
        """
        self.ensure_one()
        res = {}
        account = self.product_id.property_account_income_id or self.product_id.categ_id.property_account_income_categ_id
        fpos = self.testreq_id.customer_id.property_account_position_id or False
        if not account:
            journal = self.env['account.invoice'].default_get(['journal_id'])['journal_id']
            if not journal:
                raise UserError(_('Please define an accounting sales journal for this company.'))
            
            journal = self.env['account.journal'].sudo().browse(journal)
            account = journal.default_credit_account_id
        fpos = self.testreq_id.customer_id.property_account_position_id or False
        if fpos:
            account = fpos.map_account(account)

        res = {
            'name': self.name,
            # 'sequence': self.sequence,
            'origin': self.testreq_id.name,
            'account_id': account.id,
            'price_unit': self.price_unit,
            'quantity': self.product_qty,
            'discount': self.discount,
            # 'uom_id': self.product_uom.id,
            'product_id': self.product_id.id,
            # 'layout_category_id': self.layout_category_id and self.layout_category_id.id or False,
            'invoice_line_tax_ids': [(6, 0, self.tax_id.ids)],
            # 'account_analytic_id': analytic_account_id.id,
            # 'analytic_tag_ids': [(6, 0, self.analytic_tag_ids.ids)],
        }
        return res

    @api.multi
    def testreq_invoice_line_create(self, invoice_id):
        """ Create an invoice line.
        """
        invoice_lines = self.env['account.invoice.line']
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for line in self:
            if not float_is_zero(line.product_qty, precision_digits=precision):
                vals = line.prepare_testreq_invoice_line()
                vals.update({'invoice_id': invoice_id, })
                invoice_lines = self.env['account.invoice.line'].create(vals)

        return invoice_lines
