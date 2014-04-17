# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,

#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import sys
import io
import base64
import urllib2
from datetime import datetime, timedelta

from jinja2 import Template

from openerp.tools import DEFAULT_SERVER_DATE_FORMAT, DEFAULT_SERVER_DATETIME_FORMAT, DATETIME_FORMATS_MAP, float_compare
from openerp import pooler, tools
from dateutil.relativedelta import relativedelta
from openerp.osv import fields, osv
from openerp import netsvc
from openerp.tools.translate import _
import pytz
from openerp import SUPERUSER_ID

class ebay_message_synchronize(osv.TransientModel):
    _name = 'ebay.message.synchronize'
    _description = 'eBay message synchronize'
    
    _columns = {
        'number_of_days': fields.selection([
            ('1', '1'),
            ('2', '2'),
            ('3', '3'),
            ('5', '5'),
            ('7', '7'),
            ('15', '15'),
            ('30', '30'),
            ], 'Number Of Days'),
        'message_status': fields.selection([
            ('Unanswered', 'Unanswered'),
            ('Answered', 'Answered'),
            ('CustomCode', 'CustomCode')], 'Message Status'),
        'after_service_message': fields.boolean('After Service Message'),
        'ignoe_order_before': fields.datetime('Ignore Orders Before'),
        'sandbox_user_included': fields.boolean ('Sandbox User Included'),
    }
    
    _defaults = {
        'number_of_days': '2',
        'after_service_message': False,
        'ignoe_order_before': (datetime.now() - timedelta(35)).strftime(tools.DEFAULT_SERVER_DATETIME_FORMAT),
        'sandbox_user_included': False,
    }
    
    def view_init(self, cr, uid, fields_list, context=None):
        return False
    
    def action_sync(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        this = self.browse(cr, uid, ids)[0]
        ebay_ebay_obj = self.pool.get('ebay.ebay')
        ebay_message_obj =  self.pool.get('ebay.message')
        ebay_message_media_obj =  self.pool.get('ebay.message.media')
        ebay_sale_order_obj = self.pool.get('ebay.sale.order')
            
        if this.after_service_message:
            now_time = datetime.now()
            for user in ebay_ebay_obj.get_auth_user(cr, uid, this.sandbox_user_included, context=context):
                entries_per_page = 100
                page_number = 1
                total_number_of_entries = entries_per_page
                while total_number_of_entries == entries_per_page:
                    call_data=dict()
                    call_data['FeedbackType'] = 'FeedbackReceivedAsSeller'
                    call_data['Pagination'] = {
                        'EntriesPerPage': entries_per_page,
                        'PageNumber': page_number,
                    }
                    call_data['DetailLevel'] = 'ReturnAll'
                    error_msg = 'Get the feedback for the specified user %s' % user.name
                    reply = ebay_ebay_obj.call(cr, uid, user, 'GetFeedback', call_data, error_msg, context=context).response.reply
                    total_number_of_entries = int(reply.PaginationResult.TotalNumberOfEntries)
                    feedback_details = reply.FeedbackDetailArray.FeedbackDetail
                    if type(feedback_details) != list:
                        feedback_details = [feedback_details]
                    for feedback_detail in feedback_details:
                        if (now_time-feedback_detail.CommentTime).days > int(this.number_of_days):
                            total_number_of_entries = 0
                        domain = [('order_id','=',feedback_detail.OrderLineItemID)]
                        ids = ebay_sale_order_obj.search(cr, uid, domain, context=context)
                        if ids:
                            ebay_sale_order = ebay_sale_order_obj.browse(cr, uid, ids, context=context)[0]
                            if ebay_sale_order.state != 'done':
                                ebay_sale_order.write(dict(state='done'))
                                ebay_sale_order.refresh()
                        pass
                    pass
            # search matched order
            domain = [('state', '=', 'sent'), ('shipped_time', '>', this.ignoe_order_before)]
            ids = ebay_sale_order_obj.search(cr, uid, domain, context=context)
            if ids:
                for ebay_sale_order in ebay_sale_order_obj.browse(cr, uid, ids, context=context):
                    print ebay_sale_order.name, ebay_sale_order.sd_record_number, ebay_sale_order.state
                    '''
                    delta = now - ebay_sale_order.shipped_time
                    if delta > 7 and ebay_sale_orderafter_service_duration == '0':
                        pass
                    elif delta > 15 and ebay_sale_orderafter_service_duration == '7':
                        pass
                    elif delta > 25 and ebay_sale_orderafter_service_duration == '15':
                        pass
                    else:
                        pass
                    '''
        else:
            end_creation_time = datetime.now()
            start_creation_time = end_creation_time - timedelta(int(this.number_of_days))
            
            for user in ebay_ebay_obj.get_auth_user(cr, uid, this.sandbox_user_included, context=context):
                entries_per_page = 100
                page_number = 1
                has_more_items = True
                while has_more_items:
                    call_data=dict()
                    call_data['EndCreationTime'] = end_creation_time
                    call_data['MailMessageType'] = 'All'
                    if this.message_status:
                        call_data['MessageStatus'] = this.message_status
                    call_data['StartCreationTime'] = start_creation_time
                    call_data['Pagination'] = {
                        'EntriesPerPage': entries_per_page,
                        'PageNumber': page_number,
                    }
                    error_msg = 'Get the messages for the specified user %s' % user.name
                    reply = ebay_ebay_obj.call(cr, uid, user, 'GetMemberMessages', call_data, error_msg, context=context).response.reply
                    has_more_items = reply.HasMoreItems == 'true'
                    messages = reply.MemberMessage.MemberMessageExchange
                    if type(messages) != list:
                        messages = [messages]
                    for message in messages:
                        # find existing message
                        domain = [('message_id', '=', message.Question.MessageID), ('ebay_user_id', '=', user.id)]
                        ids = ebay_message_obj.search(cr, uid, domain, context=context)
                        if ids:
                            ebay_message = ebay_message_obj.browse(cr, uid, ids[0], context=context)
                            last_modified_date = message.LastModifiedDate
                            if ebay_message.last_modified_date != ebay_ebay_obj.to_default_format(cr, uid, last_modified_date):
                                # last modified
                                vals = dict(
                                    last_modified_date=message.LastModifiedDate,
                                    state=message.MessageStatus,
                                )
                                ebay_message.write(vals)
                                pass
                        else:
                            # create new message
                            vals = dict(
                                name=message.Question.Subject,
                                body=message.Question.Body,
                                message_type=message.Question.MessageType,
                                question_type=message.Question.QuestionType,
                                recipient_or_sender_id=message.Question.SenderID,
                                sender_email=message.Question.SenderEmail,
                                message_id=message.Question.MessageID,
                                last_modified_date=message.LastModifiedDate,
                                state=message.MessageStatus,
                                ebay_user_id=user.id,
                                type='in',
                            )
                            if message.has_key('Item'):
                                vals['item_id'] = message.Item.ItemID
                                vals['title'] = message.Item.Title
                                vals['end_time'] = message.Item.ListingDetails.EndTime
                                vals['start_time'] = message.Item.ListingDetails.StartTime
                                vals['current_price'] = message.Item.SellingStatus.CurrentPrice.value
                            ebay_message_id = ebay_message_obj.create(cr, uid, vals, context=context)
                            
                            message_medias = []
                            if message.has_key('MessageMedia'):
                                message_medias.extend(message.MessageMedia if type(message.MessageMedia) == list else [message.MessageMedia])
                            if message.Question.has_key('MessageMedia'):
                                message_medias.extend(message.Question.MessageMedia if type(message.Question.MessageMedia) == list else [message.Question.MessageMedia])
                            if message_medias:
                                for media in message_medias:
                                    vals = dict(
                                        name=media.MediaName,
                                        image=base64.encodestring(urllib2.urlopen(media.MediaURL).read()),
                                        full_url=media.MediaURL,
                                        message_id=ebay_message_id,
                                    )
                                    ebay_message_media_obj.create(cr, uid, vals, context=context)
    
                    page_number = page_number + 1
        if this.after_service_message:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Sent',
                'view_mode': 'tree,form',
                'view_type': 'form',
                'res_model': 'ebay.message',
                'domain': "[('type','=','out')]",
                'context': "{'default_type':'out'}]",
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Inbox',
                'view_mode': 'tree,form',
                'view_type': 'form',
                'res_model': 'ebay.message',
                'domain': "[('type','=','in')]",
                'context': "{'default_type':'in'}]",
            }

class ebay_message_media(osv.osv):
    _name = "ebay.message.media"
    _description = "eBay member message"
    
    def _get_image(self, cr, uid, ids, name, args, context=None):
        result = dict.fromkeys(ids, False)
        for obj in self.browse(cr, uid, ids, context=context):
            result[obj.id] = tools.image_get_resized_images(obj.image)
        return result
    
    def _set_image(self, cr, uid, id, name, value, args, context=None):
        return self.write(cr, uid, [id], {'image': tools.image_resize_image_big(value)}, context=context)
    
    def _has_image(self, cr, uid, ids, name, args, context=None):
        result = {}
        for obj in self.browse(cr, uid, ids, context=context):
            result[obj.id] = obj.image != False
        return result
    
    _columns = {
        'name': fields.char('Name', size=100, required=True),
        # image: all image fields are base64 encoded and PIL-supported
        'image': fields.binary("Image",
            help="This field holds the image used as avatar for this contact, limited to 1024x1024px"),
        'image_medium': fields.function(_get_image, fnct_inv=_set_image,
            string="Medium-sized image", type="binary", multi="_get_image",
            store={
                'ebay.message.media': (lambda self, cr, uid, ids, c={}: ids, ['image'], 10),
            },
            help="Medium-sized image of this contact. It is automatically "\
                 "resized as a 128x128px image, with aspect ratio preserved. "\
                 "Use this field in form views or some kanban views."),
        'image_small': fields.function(_get_image, fnct_inv=_set_image,
            string="Small-sized image", type="binary", multi="_get_image",
            store={
                'ebay.message.media': (lambda self, cr, uid, ids, c={}: ids, ['image'], 10),
            },
            help="Small-sized image of this contact. It is automatically "\
                 "resized as a 64x64px image, with aspect ratio preserved. "\
                 "Use this field anywhere a small image is required."),
        'has_image': fields.function(_has_image, type="boolean"),
        'full_url': fields.char('URL', readonly=True),
        'picture_format': fields.char('PictureFormat', readonly=True),
        'use_by_date': fields.datetime('UseByDate', readonly=True),
        'message_id': fields.many2one('ebay.message', 'Message', readonly=True, ondelete='cascade'),
    }
    
ebay_message_media()
    
class ebay_message(osv.osv):
    _name = "ebay.message"
    _description = "eBay member message"
    
    def _get_message_chat(self, cr, uid, ids, field_name, arg, context):
        if context is None:
            context = {}
        ebay_message_obj =  self.pool.get('ebay.message')
        template = '''
{{ sender_id }}    {{ last_modified_date }}
----------------------------------------------------------
{{ body }}


        '''
        chat_template = Template(template)
        res = {}
        for record in self.browse(cr, uid, ids, context=context):
            res[record.id] = ''
            ebay_user_id = record.recipient_or_sender_id
            item_id = record.item_id
            last_modified_date = record.last_modified_date
            if ebay_user_id and item_id:
                domain = [('recipient_or_sender_id', '=', ebay_user_id), ('item_id', '=', item_id), ('last_modified_date', '<', last_modified_date)]
                ids = ebay_message_obj.search(cr, uid, domain, context=context)
                if ids:
                    chat = ''
                    for msg in ebay_message_obj.browse(cr, uid, ids, context=context):
                        chat += chat_template.render(
                            sender_id=msg.recipient_or_sender_id if msg.type == 'in' else msg.ebay_user_id.name,
                            last_modified_date=msg.last_modified_date,
                            body=msg.body,
                        )
                    res[record.id] = chat
        return res

    _columns = {
        'name': fields.char('Subject', required=True),
        'body': fields.text('Body'),
        'message_type': fields.selection([
            ('All', 'All'),
            ('AskSellerQuestion', 'AskSellerQuestion'),
            ('ClassifiedsBestOffer', 'ClassifiedsBestOffer'),
            ('ClassifiedsContactSeller', 'ClassifiedsContactSeller'),
            ('ContactEbayMember', 'ContactEbayMember'),
            ('ContacteBayMemberViaAnonymousEmail', 'ContacteBayMemberViaAnonymousEmail'),
            ('ContacteBayMemberViaCommunityLink', 'ContacteBayMemberViaCommunityLink'),
            ('ContactMyBidder', 'ContactMyBidder'),
            ('ContactTransactionPartner', 'ContactTransactionPartner'),
            ('CustomCode', 'CustomCode'),
            ('ResponseToASQQuestion', 'ResponseToASQQuestion'),
            ('ResponseToContacteBayMember', 'ResponseToContacteBayMember'),
            ], 'MessageType', readonly=True),
        'question_type': fields.selection([
            ('CustomCode', 'CustomCode'),
            ('CustomizedSubject', 'CustomizedSubject'),
            ('General', 'General'),
            ('MultipleItemShipping', 'MultipleItemShipping'),
            ('None', 'None'),
            ('Payment', 'Payment'),
            ('Shipping', 'Shipping'),
        ], 'QuestionType'),
        'recipient_or_sender_id': fields.char('Recipient / Sender'),
        'sender_email': fields.char('Sender Email', size=240),
        
        'item_id': fields.char('Item ID', size=38),
        'title': fields.char('Title', readonly=True),
        'end_time': fields.datetime('End Time', readonly=True),
        'start_time': fields.datetime('Start Time', readonly=True),
        'current_price': fields.float('CurrentPrice', readonly=True),
        
        'media_ids': fields.one2many('ebay.message.media', 'message_id', 'Media'),
        'message_id': fields.char('MessageID', help='ID that uniquely identifies a message for a given user.'),
        'last_modified_date': fields.datetime('LastModifiedDate', readonly=True),
        'state': fields.selection([
            ('Draft', 'Draft'),
            ('Sent', 'Sent'),
            ('CustomCode', 'CustomCode'),
            ('Unanswered', 'Unanswered'),
            ('Answered', 'Answered'),], 'MessageStatus', readonly=True),
        'chat': fields.function(_get_message_chat, type='text', method="True", string='Chat', readonly=True),
        'type': fields.selection([
            ('in', 'in'),
            ('out', 'out'),
        ], 'Type', required=True, readonly=True, select=True),
        'partner_id': fields.many2one('res.partner', 'Customer'),
        'ebay_user_id': fields.many2one('ebay.user', 'eBay User', readonly=True),
        'order_id': fields.many2one('ebay.sale.order', 'Order Reference', ondelete='cascade'),
    }
    
    _defaults = {
        'question_type': 'General',
        'state': 'Draft',
        'type': 'out',
    }
    
    _order = 'last_modified_date desc'
    
    def action_reply(self, cr, uid, ids, context=None):
        for msg in self.browse(cr, uid, ids, context=context):
            pass
    
    def action_send(self, cr, uid, ids, context=None):
        for msg in self.browse(cr, uid, ids, context=context):
            pass
    
ebay_message()

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: