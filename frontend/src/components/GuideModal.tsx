/** GuideModal — in-app modal for displaying workflow guides in Nepali/English. */
import React, { useState, useEffect } from 'react';
import { Modal, Tabs, Spin, Button, Tooltip } from 'antd';
import { VideoCameraOutlined, DownloadOutlined, GlobalOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import DOMPurify from 'dompurify';
import '../styles/GuideModal.css';

interface GuideMeta {
  id: string;
  title: string;
  titleNp: string;
  file: string;
  estimatedTime: string;
}

interface GuideModalProps {
  visible: boolean;
  onClose: () => void;
  initialGuide?: string;
}

const GUIDES: GuideMeta[] = [
  {
    id: 'forest-boundary',
    title: 'Forest Boundary Upload',
    titleNp: 'वन सीमा अपलोड',
    file: '01-forest-boundary-upload.md',
    estimatedTime: '3 min',
  },
  {
    id: 'blocks-compartments',
    title: 'Block & Compartment Creation',
    titleNp: 'ब्लक र कम्पार्टमेन्ट सिर्जना',
    file: '02-block-compartment-creation.md',
    estimatedTime: '5 min',
  },
  {
    id: 'inventory-upload',
    title: 'Inventory CSV Upload',
    titleNp: 'इनभेन्टरी CSV अपलोड',
    file: '03-inventory-csv-upload.md',
    estimatedTime: '4 min',
  },
  {
    id: 'sampling-design',
    title: 'Sampling Design',
    titleNp: 'नमूना डिजाइन',
    file: '04-sampling-design.md',
    estimatedTime: '5 min',
  },
  // Future guides:
  // { id: 'op-generation', title: 'OP Generation', titleNp: 'कार्ययोजना जनरेट', file: '05-op-generation.md', estimatedTime: '8 min' },
  // { id: 'yearly-activities', title: 'Yearly Activities', titleNp: 'वार्षिक गतिविधि', file: '06-yearly-activities.md', estimatedTime: '4 min' },
];

const GuideModal: React.FC<GuideModalProps> = ({ visible, onClose, initialGuide }) => {
  const { t } = useTranslation();
  const [activeGuide, setActiveGuide] = useState<string>(initialGuide || GUIDES[0].id);
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [lang, setLang] = useState<'np' | 'en'>('np');

  useEffect(() => {
    loadGuide(activeGuide);
  }, [activeGuide, lang]);

  const loadGuide = async (guideId: string) => {
    setLoading(true);
    try {
      const guide = GUIDES.find(g => g.id === guideId);
      if (!guide) return;

      // In production, these would be pre-loaded or served from a CDN
      // For now, fetch from public folder or use dynamic import
      const response = await fetch(`/guides/${guide.file}`);
      if (response.ok) {
        const markdown = await response.text();
        setContent(markdown);
      } else {
        setContent(t('guides.notFound'));
      }
    } catch {
      setContent(t('guides.loadError'));
    } finally {
      setLoading(false);
    }
  };

  const renderContent = () => {
    if (loading) {
      return (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin size="large" />
          <p style={{ marginTop: 16, color: '#999' }}>{t('guides.loading')}</p>
        </div>
      );
    }

    // Sanitised before it reaches the DOM (S4-46 / H6.11), matching
    // Report/ReportTab.tsx, which already did this correctly — the
    // inconsistency between the two was unintentional.
    //
    // The guides are static files under public/guides/ today, so this is not
    // an exploitable hole right now. It is the moment guide content becomes
    // remotely sourced or admin-editable that it would silently turn into a
    // stored-XSS sink, with no code change to notice. `simpleMarkdownToHtml`
    // below is a hand-rolled regex converter that neither escapes nor strips
    // anything, so raw <script> in a guide would pass straight through.
    return (
      <div
        className="guide-markdown"
        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(simpleMarkdownToHtml(content)) }}
      />
    );
  };

  // Very basic markdown to HTML - replace with marked.js or react-markdown in production
  const simpleMarkdownToHtml = (md: string): string => {
    return md
      .replace(/^### (.*$)/gim, '<h3>$1</h3>')
      .replace(/^## (.*$)/gim, '<h2>$1</h2>')
      .replace(/^# (.*$)/gim, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/gim, '<em>$1</em>')
      .replace(/`(.*?)`/gim, '<code>$1</code>')
      .replace(/\n\n/gim, '</p><p>')
      .replace(/^- (.*$)/gim, '<li>$1</li>')
      .replace(/^\d+\. (.*$)/gim, '<li>$1</li>')
      .replace(/<li>/gim, '<ul><li>')
      .replace(/<\/li>/gim, '</li></ul>')
      .replace(/\|(.+)\|/gim, '<tr><td>$1</td></tr>') // Very rough table handling
      .replace(/^---$/gim, '<hr />');
  };

  const activeGuideMeta = GUIDES.find(g => g.id === activeGuide);

  return (
    <Modal
      title={activeGuideMeta ? (lang === 'np' ? activeGuideMeta.titleNp : activeGuideMeta.title) : ''}
      open={visible}
      onCancel={onClose}
      width={900}
      centered
      className="guide-modal"
      footer={[
        <Tooltip key="video" title={t('guides.videoTooltip')}>
          <Button type="default" icon={<VideoCameraOutlined />} onClick={() => window.open('https://example.com/videos', '_blank')}>
            {t('guides.watchVideo')}
          </Button>
        </Tooltip>,
        <Tooltip key="download" title={t('guides.downloadTooltip')}>
          <Button type="default" icon={<DownloadOutlined />} onClick={() => downloadGuide(activeGuide)}>
            {t('guides.downloadPDF')}
          </Button>
        </Tooltip>,
        <Tooltip key="web" title={t('guides.webTooltip')}>
          <Button type="default" icon={<GlobalOutlined />} onClick={() => window.open(`/guides/${activeGuide}.html`, '_blank')}>
            {t('guides.viewWeb')}
          </Button>
        </Tooltip>,
        <Button key="close" type="default" onClick={onClose}>
          {t('common.close')}
        </Button>,
        <Button key="ok" type="primary" onClick={onClose}>
          {t('common.gotIt')}
        </Button>,
      ]}
    >
      <div style={{ marginBottom: 16 }}>
        <Tabs
          defaultActiveKey={activeGuide}
          onChange={setActiveGuide}
          items={GUIDES.map(g => ({
            key: g.id,
            label: lang === 'np' ? g.titleNp : g.title,
          }))}
          className="guide-tabs"
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12, gap: 8 }}>
          <Button
            type={lang === 'np' ? 'primary' : 'default'}
            size="small"
            onClick={() => setLang('np')}
          >
            नेपाली
          </Button>
          <Button
            type={lang === 'en' ? 'primary' : 'default'}
            size="small"
            onClick={() => setLang('en')}
          >
            English
          </Button>
        </div>
        {renderContent()}
      </div>
    </Modal>
  );
};

const downloadGuide = (guideId: string) => {
  const guide = GUIDES.find(g => g.id === guideId);
  if (!guide) return;

  // In production, this would trigger a PDF generation endpoint
  const link = document.createElement('a');
  link.href = `/guides/${guide.file}`;
  link.download = `${guide.id}-guide.md`;
  link.click();
};

export default GuideModal;