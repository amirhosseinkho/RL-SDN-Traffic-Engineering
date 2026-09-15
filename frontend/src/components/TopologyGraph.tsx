import { useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import type { GraphNode, GraphEdge, LinkMetric } from '../types';

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  linkMetrics?: LinkMetric[];
  width?: number;
  height?: number;
}

function getEdgeColor(utilization: number): string {
  if (utilization > 0.9) return '#ef4444';
  if (utilization > 0.7) return '#f97316';
  if (utilization > 0.4) return '#eab308';
  return '#22c55e';
}

function getNodeColor(nodeType: string): string {
  return nodeType === 'switch' ? '#3b82f6' : '#8b5cf6';
}

export function TopologyGraph({ nodes, edges, linkMetrics = [], width = 800, height = 500 }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  const getUtilization = useCallback(
    (src: string, dst: string): number => {
      const srcDpid = nodes.find((n) => n.id === src)?.dpid;
      const dstDpid = nodes.find((n) => n.id === dst)?.dpid;
      if (!srcDpid || !dstDpid) return 0;
      const metric = linkMetrics.find(
        (m) => m.src_dpid === srcDpid && m.dst_dpid === dstDpid
      );
      return metric?.utilization ?? 0;
    },
    [nodes, linkMetrics]
  );

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const g = svg.append('g');

    // Zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    // Arrow markers
    svg.append('defs').selectAll('marker')
      .data(['arrow'])
      .join('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('fill', '#64748b')
      .attr('d', 'M0,-5L10,0L0,5');

    const simulation = d3.forceSimulation(nodes as d3.SimulationNodeDatum[])
      .force('link', d3.forceLink(
        edges.map((e) => ({
          ...e,
          source: e.source,
          target: e.target,
        }))
      ).id((d: d3.SimulationNodeDatum) => (d as GraphNode).id).distance(80))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide(30));

    // Draw edges
    const link = g.append('g')
      .selectAll('line')
      .data(edges)
      .join('line')
      .attr('stroke', (d) => getEdgeColor(getUtilization(d.source, d.target)))
      .attr('stroke-width', 2)
      .attr('stroke-opacity', 0.8)
      .attr('marker-end', 'url(#arrow)');

    // Edge utilization labels
    const linkLabel = g.append('g')
      .selectAll('text')
      .data(edges)
      .join('text')
      .attr('fill', '#94a3b8')
      .attr('font-size', '9px')
      .attr('text-anchor', 'middle')
      .text((d) => {
        const u = getUtilization(d.source, d.target);
        return u > 0 ? `${(u * 100).toFixed(0)}%` : '';
      });

    // Draw nodes
    const node = g.append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'pointer')
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            (d as d3.SimulationNodeDatum).fx = (d as d3.SimulationNodeDatum).x;
            (d as d3.SimulationNodeDatum).fy = (d as d3.SimulationNodeDatum).y;
          })
          .on('drag', (event, d) => {
            (d as d3.SimulationNodeDatum).fx = event.x;
            (d as d3.SimulationNodeDatum).fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            (d as d3.SimulationNodeDatum).fx = null;
            (d as d3.SimulationNodeDatum).fy = null;
          })
      );

    node.append('circle')
      .attr('r', (d) => (d.node_type === 'switch' ? 16 : 10))
      .attr('fill', (d) => getNodeColor(d.node_type))
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 2);

    node.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.3em')
      .attr('fill', 'white')
      .attr('font-size', (d) => (d.node_type === 'switch' ? '9px' : '7px'))
      .attr('font-weight', '600')
      .text((d) => d.label);

    node.append('title').text((d) => `${d.label}\nType: ${d.node_type}${d.ip ? `\nIP: ${d.ip}` : ''}${d.dpid ? `\nDPID: ${d.dpid}` : ''}`);

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      linkLabel
        .attr('x', (d: any) => (d.source.x + d.target.x) / 2)
        .attr('y', (d: any) => (d.source.y + d.target.y) / 2);

      node.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => simulation.stop();
  }, [nodes, edges, linkMetrics, width, height, getUtilization]);

  return (
    <div className="relative w-full rounded-xl overflow-hidden bg-slate-900 border border-slate-700">
      {/* Legend */}
      <div className="absolute top-3 right-3 flex flex-col gap-1 text-xs z-10">
        {[
          { color: '#22c55e', label: '< 40%' },
          { color: '#eab308', label: '40–70%' },
          { color: '#f97316', label: '70–90%' },
          { color: '#ef4444', label: '> 90%' },
        ].map(({ color, label }) => (
          <div key={label} className="flex items-center gap-1.5">
            <div className="w-3 h-1.5 rounded" style={{ backgroundColor: color }} />
            <span className="text-slate-400">{label}</span>
          </div>
        ))}
      </div>
      <div className="absolute top-3 left-3 flex gap-3 text-xs z-10">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-blue-500" />
          <span className="text-slate-400">Switch</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-violet-500" />
          <span className="text-slate-400">Host</span>
        </div>
      </div>
      <svg ref={svgRef} width="100%" height={height} className="block" />
    </div>
  );
}
