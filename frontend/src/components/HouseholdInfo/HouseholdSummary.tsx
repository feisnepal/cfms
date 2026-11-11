/**
 * Household Summary Dashboard
 * Displays aggregate statistics and charts
 */
import React, { useState } from 'react';
import { Card, Row, Col, Statistic, Tag, Divider, Collapse } from 'antd';
import {
  UserOutlined,
  HomeOutlined,
  TeamOutlined,
  FireOutlined,
  GoldOutlined,
  EnvironmentOutlined,
} from '@ant-design/icons';
import { Pie, Bar } from 'react-chartjs-2';
import '../../utils/chartSetup';
import type { HouseholdSummary } from '../../types/household';
import HouseholdVariablePanel from './HouseholdVariablePanel';
import { useT } from '../../i18n/hooks';

const BHARI_KG = 30;

interface HouseholdSummaryDashboardProps {
  summary: HouseholdSummary;
  calculationId?: string;
}

const HouseholdSummaryDashboard: React.FC<HouseholdSummaryDashboardProps> = ({
  summary,
  calculationId,
}) => {

  const t = useT();  // Prepare caste distribution chart data
  const casteData = Object.entries(summary.caste_distribution).map(
    ([name, value]) => ({ name, value })
  );

  // Prepare prosperity distribution chart data
  const prosperityData = Object.entries(summary.prosperity_distribution).map(
    ([name, value]) => ({ name, value })
  );

  // Colors for pie charts
  const CASTE_COLORS = ['#1890ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2'];
  const PROSPERITY_COLORS = {
    'सम्पन्न': '#52c41a',
    'मध्यम': '#1890ff',
    'विपन्न': '#faad14',
    'अति विपन्न': '#f5222d',
  };

  return (
    <div>
      {/* Summary Cards */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={8} lg={6}>
          <Card>
            <Statistic
              title={t('household.summary.totalHouseholds')}
              value={summary.total_households}
              prefix={<HomeOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
            <p className="text-xs text-gray-400 font-mono mt-1">{'{{hh_total_households}}'}</p>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={6}>
          <Card>
            <Statistic
              title={t('household.summary.totalPopulation')}
              value={summary.total_population}
              prefix={<TeamOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
            <p className="text-xs text-gray-400 font-mono mt-1">{'{{hh_total_population}}'}</p>
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              Male: {summary.total_male} | Female: {summary.total_female}
            </div>
            <div className="flex gap-2 mt-1">
              <p className="text-xs text-gray-400 font-mono">{'{{hh_total_male}}'}</p>
              <p className="text-xs text-gray-400 font-mono">{'{{hh_total_female}}'}</p>
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={6}>
          <Card>
            <Statistic
              title={t('household.summary.forestDependent')}
              value={summary.forest_dependent_households}
              prefix={<EnvironmentOutlined />}
              suffix={`/ ${summary.total_households}`}
              valueStyle={{ color: '#52c41a' }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              {((summary.forest_dependent_households / summary.total_households) * 100).toFixed(1)}%
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8} lg={6}>
          <Card>
            <Statistic
              title={t('household.summary.avgLandArea')}
              value={summary.avg_land_area ? Number(summary.avg_land_area).toFixed(2) : 0}
              suffix="units"
              prefix={<GoldOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
      </Row>

      <Divider>{t('household.summary.livestock')}</Divider>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title={t('household.summary.cows')}
              value={summary.total_cow_ox}
              valueStyle={{ color: '#8b4513' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title={t('household.summary.buffaloes')}
              value={summary.total_buffalo}
              valueStyle={{ color: '#2f4f4f' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title={t('household.summary.goats')}
              value={summary.total_goat_sheep}
              valueStyle={{ color: '#696969' }}
            />
          </Card>
        </Col>
      </Row>

      <Divider>{t('household.summary.demands')}</Divider>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title={t('household.summary.firewood')}
              value={Number(summary.total_firewood_demand_bhari).toFixed(1)}
              suffix={t('household.summary.bhari')}
              prefix={<FireOutlined />}
              valueStyle={{ color: '#ff4d4f' }}
            />
            <p className="text-xs text-gray-400 font-mono mt-1">{'{{hh_firewood_demand_bhari}}'}</p>
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              {(Number(summary.total_firewood_demand_bhari) * BHARI_KG).toFixed(0)} kg
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title={t('household.summary.grass')}
              value={Number(summary.total_grass_demand_bhari).toFixed(1)}
              suffix={t('household.summary.bhari')}
              valueStyle={{ color: '#52c41a' }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              {(Number(summary.total_grass_demand_bhari) * BHARI_KG).toFixed(0)} kg
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title={t('household.summary.bedding')}
              value={Number(summary.total_bedding_demand_bhari).toFixed(1)}
              suffix={t('household.summary.bhari')}
              valueStyle={{ color: '#faad14' }}
            />
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              {(Number(summary.total_bedding_demand_bhari) * BHARI_KG).toFixed(0)} kg
            </div>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title={t('household.summary.timber')}
              value={Number(summary.total_timber_demand_cft).toFixed(1)}
              suffix="cft"
              valueStyle={{ color: '#8b4513' }}
            />
            <p className="text-xs text-gray-400 font-mono mt-1">{'{{hh_timber_demand_cft}}'}</p>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={8}>
          <Card>
            <Statistic
              title={t('household.summary.poles')}
              value={summary.total_pole_demand}
              suffix="poles"
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>

      <Divider>{t('household.summary.distribution')}</Divider>

      <Row gutter={[16, 16]}>
        {/* Caste Distribution */}
        <Col xs={24} lg={12}>
          <Card title={t('household.summary.casteDistribution')} size="small">
            <p className="text-xs text-gray-400 font-mono mb-1">{'{{chart:hh_caste_pie}}'}</p>
            <p className="text-xs text-gray-400 font-mono mb-1">{'{{hh_caste_distribution}}'}</p>
            {casteData.length > 0 ? (
              <>
                <div style={{ width: '100%', height: 300 }}>
                  <Pie
                    height={300}
                    data={{
                      labels: casteData.map((d) => d.name),
                      datasets: [{
                        data: casteData.map((d) => d.value),
                        backgroundColor: casteData.map((_, index) => CASTE_COLORS[index % CASTE_COLORS.length]),
                        borderColor: '#fff',
                        borderWidth: 1,
                      }],
                    }}
                    options={{
                      plugins: {
                        legend: { display: false },
                        tooltip: {
                          callbacks: {
                            label: (ctx) => `${ctx.label}: ${ctx.parsed}`,
                          },
                        },
                      },
                    }}
                  />
                </div>
                <div style={{ marginTop: 16 }}>
                  {casteData.map((item, index) => (
                    <Tag
                      key={item.name}
                      color={CASTE_COLORS[index % CASTE_COLORS.length]}
                      style={{ marginBottom: 8 }}
                    >
                      {item.name}: {item.value}
                    </Tag>
                  ))}
                </div>
              </>
            ) : (
              <p>{t('household.summary.noCaste')}</p>
            )}
          </Card>
        </Col>

        {/* Prosperity Distribution */}
        <Col xs={24} lg={12}>
          <Card title={t('household.summary.prosperityDistribution')} size="small">
            <p className="text-xs text-gray-400 font-mono mb-1">{'{{chart:hh_prosperity_bar}}'}</p>
            <p className="text-xs text-gray-400 font-mono mb-1">{'{{hh_prosperity_distribution}}'}</p>
            {prosperityData.length > 0 ? (
              <>
                <div style={{ width: '100%', height: 300 }}>
                  <Bar
                    height={300}
                    data={{
                      labels: prosperityData.map((d) => d.name),
                      datasets: [{
                        label: t('household.summary.count'),
                        data: prosperityData.map((d) => d.value),
                        backgroundColor: prosperityData.map((entry) =>
                          PROSPERITY_COLORS[entry.name as keyof typeof PROSPERITY_COLORS] || '#1890ff'
                        ),
                      }],
                    }}
                    options={{
                      plugins: { legend: { display: false } },
                      scales: {
                        x: { grid: { display: true } },
                        y: { beginAtZero: true },
                      },
                    }}
                  />
                </div>
                <div style={{ marginTop: 16 }}>
                  {prosperityData.map((item) => (
                    <Tag
                      key={item.name}
                      color={PROSPERITY_COLORS[item.name as keyof typeof PROSPERITY_COLORS]}
                      style={{ marginBottom: 8 }}
                    >
                      {item.name}: {item.value}
                    </Tag>
                  ))}
                </div>
              </>
            ) : (
              <p>{t('household.summary.noProsperity')}</p>
            )}
          </Card>
        </Col>
      </Row>

      <Divider>{t('household.summary.notes')}</Divider>

      <Card size="small">
        <p style={{ marginBottom: 8 }}>
          <strong>{t('household.summary.bhariKg', { kg: BHARI_KG })}</strong>
        </p>
        <p style={{ marginBottom: 8 }}>
          {t('household.summary.notesYearly')}
        </p>
        <p style={{ marginBottom: 0 }}>
          {t('household.summary.formulas')}
        </p>
        <ul style={{ marginTop: 8, paddingLeft: 20, fontSize: 12, color: '#666' }}>
          <li>Firewood: (population × 250 + cattle × 600) kg/year ÷ {BHARI_KG}</li>
          <li>Grass: (cow×20 + buffalo×30 + goat×5) kg/day × 365 ÷ {BHARI_KG}</li>
          <li>Bedding: (cow + buffalo) × 10 kg/day × 365 ÷ {BHARI_KG}</li>
        </ul>
      </Card>

      {calculationId && (
        <div style={{ marginTop: 24 }}>
          <HouseholdVariablePanel
            calculationId={calculationId}
            tabKey="summary"
            onInsert={(varStr) => {
              const ta = document.getElementById('summary-notes') as HTMLTextAreaElement;
              if (ta) {
                const start = ta.selectionStart;
                const end = ta.selectionEnd;
                ta.value = ta.value.substring(0, start) + varStr + ta.value.substring(end);
                ta.focus();
                ta.selectionStart = ta.selectionEnd = start + varStr.length;
              }
            }}
          />
          <div style={{
            border: '1px solid #d9d9d9',
            borderRadius: 6,
            padding: 12,
            background: '#fafafa',
            marginTop: 12,
          }}>
            <h4 style={{ margin: '0 0 8px 0', fontSize: 13 }}>
              {t('household.summary.additionalNotes')}
            </h4>
            <textarea
              id="summary-notes"
              rows={3}
              style={{
                width: '100%',
                border: '1px solid #d9d9d9',
                borderRadius: 4,
                padding: '8px 12px',
                fontSize: 13,
                lineHeight: 1.6,
                fontFamily: 'inherit',
                resize: 'vertical',
              }}
              placeholder={t('household.summary.insertHint')}
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default HouseholdSummaryDashboard;
