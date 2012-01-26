# -*- coding: utf-8 -*-
import logging
from zope import interface, schema
from zope.formlib import form
from zope.component import getUtility
from zope.app.component.hooks import getSite

from five.formlib import formbase

from Products.CMFCore.utils import getToolByName
from Products.statusmessages.interfaces import IStatusMessage

from plone.registry.interfaces import IRegistry

from collective.simserver.core import simserverMessageFactory as _
from collective.simserver.core.interfaces import ISimserverSettingsSchema
from collective.simserver.core import utils



logger = logging.getLogger('collective.simserver.core')

# Ignore articles shorter than ARTICLE_MIN_CHARS characters.
ARTICLE_MIN_CHARS = 700

class IExportForm(interface.Interface):
    ''' Form fields for the export form '''
    export_to_fs = schema.Bool(
        title=_(u'Export to filesystem'),
        description=_(u"""Export all the documents to the filesystem
                    for later processing"""),
        required=False,
        readonly=False,
        default=False,
        )

    process_directly = schema.Bool(
        title=_(u'Process directly'),
        description=_(u"""send the documents directly to the simserver"""),
        required=False,
        readonly=False,
        default=False,
        )


    upload_chunked = schema.Int(
        title = _(u'Chunksize'),
        description = _(u"""send n documents at a time (saves RAM but slower)
                    only applicable for online indexing """),
        required = False,
        readonly = False,
        default = 200,
        min = 0,
        max = 5000,
        )



    @interface.invariant
    def neither_export_nor_direct(export):
        if not export.export_to_fs and not export.process_directly:
            raise interface.Invalid(_("""Please specify if you want to
                    export and/or process directly"""))


class ExportCorpus(formbase.PageForm):

    form_fields = form.FormFields(IExportForm)
    label = _(u'Create a corpus or index documents')
    description = _(u'''You can either export the documents or send
        them directly to the simserver''')
    buffer = []

    def __init__( self, context, request ):
        registry = getUtility(IRegistry)
        self.settings = registry.forInterface(ISimserverSettingsSchema)
        self.settinguid= self.settings.corpus_collection
        if self.settings.export_path .endswith('/'):
            self.path = self.settings.export_path
        else:
            self.path = self.settings.export_path + '/'
        super( ExportCorpus, self).__init__( context, request )
        #self.results = self.context.queryCatalog()
        try:
            self.service = utils.SimService()
            response = self.service.status()
            if response['status'] == 'OK':
                IStatusMessage(self.request).addStatusMessage(
                        response['response'], type='info')
            else:
                IStatusMessage(self.request).addStatusMessage(
                        response['response'], type='error')
        except:
            status = _(u'Error connecting to simserver')
            IStatusMessage(self.request).addStatusMessage(status, type='error')


    def buffer_documents(self, brains, path, online=False,
            offline=True, min_chars=ARTICLE_MIN_CHARS):
        i=0
        for brain in brains:
            ob = brain.getObject()
            id = ob.getId()
            text = ob.SearchableText()
            text = text.strip()
            text = text.lstrip(id).lstrip()
            text = text.decode('utf-8', 'ignore')
            uid = ob.UID()
            if len(text) < min_chars:
                continue
            else:
                if online:
                    self.buffer.append({'id': uid, 'text': text})
                    logger.info('bufferd %s' % uid)
                if offline:
                    fname = path + uid
                    f = open(fname, 'w')
                    f.write(text)
                    f.flush()
                    f.close()
                    i += 1
                    logger.info('exported %s' % fname)
        return i

    @property
    def next_url(self):
        url = self.context.absolute_url()
        return url

    @form.action('train')
    def actionTrain(self, action, data):
        contextuid = self.context.UID()
        path = self.path + 'corpus/'
        site = getSite()
        online = data['process_directly']
        offline = data['export_to_fs']
        if contextuid != self.settinguid:
            topic = site.reference_catalog.lookupObject(self.settinguid)
            next_url = topic.absolute_url() + '/@@' + self.__name__
            status = _(u"""you can only train documents on the topic
                            you specified in the controlpanel""")
            IStatusMessage(self.request).addStatusMessage(status,
                                                type='error')
            status = _('you have been redirected to this topic')
            IStatusMessage(self.request).addStatusMessage(status,
                                                    type='info')
            self.request.response.redirect(next_url)
        else:
            try:
                i = self.buffer_documents(self.context.queryCatalog(),
                                                path, online, offline)
                if online:
                    logger.info('exported %i documents. Start training' % i)
                    respone = self.service.train(self.buffer)
                    if response['status'] == 'OK':
                        logger.info('training complete')
                        status = _('changes commited, index trained')
                        IStatusMessage(self.request).addStatusMessage(
                                                status, type='info')
                    else:
                        IStatusMessage(self.request).addStatusMessage(
                                    response['response'], type='error')
                else:
                    logger.info('exported %i documents.' % i)
                    status = _('export successfull')
                    IStatusMessage(self.request).addStatusMessage(
                                            status, type='info')
                self.request.response.redirect(self.next_url)
            except:
                status = _(u'error building corpus, index unchanged')
                logger.warn(status)
                IStatusMessage(self.request).addStatusMessage(status,
                                                type='error')


    @form.action('index')
    def actionIndex(self, action, data):
        path = self.path + 'index/'
        contextuid = self.context.UID()
        online = data['process_directly']
        offline = data['export_to_fs']
        chunksize = data['upload_chunked']
        if chunksize and online:
            j = 0
            k = 0
            qresults = self.context.queryCatalog()
            while j*chunksize < len(qresults):
                i = self.buffer_documents(qresults[j*chunksize:(j+1)*chunksize],
                                path, online, offline)
                j += 1
                response = self.service.index(self.buffer)
                if response['status'] == 'OK':
                    logger.info('indexed %i documents' % response['response'])
                    k += response['response']
                else:
                    logger.info(response['response'])
                self.buffer =[]
            logger.info('indexing complete, indexed %i documents' % k)
            status = _(u'changes commited, index trained')
            IStatusMessage(self.request).addStatusMessage(status, type='info')

        elif online:
            i = self.buffer_documents(self.context.queryCatalog(),
                    path, online, offline, 300)
            response = self.service.index(self.buffer)
            if response['status'] == 'OK':
                logger.info('indexing complete, indexed %i documents' %
                                            response['response'])
                status = _(u'documents indexed')
                IStatusMessage(self.request).addStatusMessage(status, type='info')
            else:
                logger.info(response['response'])
                IStatusMessage(self.request).addStatusMessage(
                                    response['response'], type='error')
        else:
            status = _('documents exported')
            IStatusMessage(self.request).addStatusMessage(status,
                                                type='info')
            logger.info('exported %i documents' % i)
        self.request.response.redirect(self.next_url)


    @form.action('Cancel')
    def actionCancel(self, action, data):
        self.request.response.redirect(self.next_url)
