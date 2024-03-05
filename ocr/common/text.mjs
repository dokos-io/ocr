import { exec } from "child_process";
import { readFile, writeFile } from "fs/promises";

import {
	Document,
	Paragraph,
	Packer,
	SectionType,
	convertMillimetersToTwip as Mm,
	PageTextDirectionType,
	Table,
	TableRow,
	TableCell,
	TableAnchorType,
	OverlapType,
	WidthType,
	TableLayoutType,
} from "docx";


function makePageSize(w = 210, h = 297) {
	const width = Mm(w);
	const height = Mm(h);
	const orientation = (width > height) ? "landscape" : "portrait";
	return { width, height, orientation };
}

function Pct(rect, pageSize = makePageSize()) {
	return {
		x: rect.x * pageSize.width,
		y: rect.y * pageSize.height,
		width: rect.width * pageSize.width,
		height: rect.height * pageSize.height,
	};
}

const textBoxMaker = (pageSize) => (text, rect) => {
	const rr = Pct(rect, pageSize);
	return new Table({
		rows: [
			new TableRow({
				children: [
					new TableCell({
						children: [new Paragraph(text)],
					}),
				],
			}),
		],
		layout: TableLayoutType.FIXED,
		margins: {
			top: 0,
			bottom: 0,
			left: 0,
			right: 0,
		},
		float: {
			absoluteHorizontalPosition: rr.x,
			absoluteVerticalPosition: rr.y,
			horizontalAnchor: TableAnchorType.PAGE,
			verticalAnchor: TableAnchorType.PAGE,
			overlap: OverlapType.OVERLAP,
		},
		width: {
			size: rr.width * 1.2,
			type: WidthType.DXA,
		},
		borders: {
			top: { style: "none" },
			right: { style: "none" },
			bottom: { style: "none" },
			left: { style: "none" },
		},
	});
};

function generateDocument(data, type="blocks", size=null) {
	const pageSize = size || makePageSize();
	const textBox = textBoxMaker(pageSize);

	function* prepareBlocks(blocks) {
		for (const block of blocks) {
			const bb = block?.Geometry?.BoundingBox;
			const txt = block?.Text;
			if (block.BlockType === "PAGE") {
				yield new Paragraph("");
			} else if (block.BlockType === "WORD") {
				// skip
			} else if (block.BlockType === "LINE") {
				if (type === "blocks") {
					yield textBox(txt, { x: bb.Left, y: bb.Top, width: bb.Width, height: bb.Height });
				} else {
					yield new Paragraph(txt);
				}
			}
		}
	}

	const doc = new Document({
		sections: [{
			properties: {
				type: SectionType.CONTINUOUS,
				page: {
					size: pageSize,
					textDirection: PageTextDirectionType.LEFT_TO_RIGHT_TOP_TO_BOTTOM,
					margin: { top: Mm(20), bottom: Mm(20), left: Mm(20), right: Mm(20) },
					pageNumbers: {
						start: 1,
						formatType: "decimal",
					},
				},
			},
			children: [...prepareBlocks(data.Blocks)],
		}],
	});
	return doc;
}

async function writeDocument(doc, path) {
	const buffer = await Packer.toBuffer(doc);
	await writeFile(path, buffer);
}

async function main() {
	// Read optional first argument
	const type = process.argv[2] || "blocks";

	// Read optional second argument
	const format = process.argv[3] || "portrait";
	let size = null;
	if (format === "landscape") {
		size = makePageSize(297, 210);
	} else {
		size = makePageSize(210, 297);
	}

	// Read from STDIN
	process.stdin.setEncoding("utf8");
	let data = "";
	for await (const chunk of process.stdin) {
		data += chunk;
	}
	const json = JSON.parse(data);
	const doc = generateDocument(json, type, size);
	const buffer = await Packer.toBuffer(doc);
	process.stdout.write(buffer);

	// const json = await readFile("test.json").then((b) => JSON.parse(b.toString()));
	// const doc = generateDocument(json);
	// await writeDocument(doc, "test2.docx");
	// exec("libreoffice --headless --convert-to pdf test2.docx");
}

main();
