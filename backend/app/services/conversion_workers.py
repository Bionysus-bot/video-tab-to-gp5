"""Picklable, bounded worker entry points; never write active project pointers."""
from pathlib import Path
from contextlib import closing
import importlib


def invoke(connection, module, function, args, kwargs):
    try:
        value = getattr(importlib.import_module(module), function)(*args, **kwargs)
        connection.send((True, value))
    except BaseException as exc:
        connection.send((False, f'{type(exc).__name__}: {str(exc)[:500]}'))
    finally:
        connection.close()


def serve(connection):
    """Keep the OCR session warm for successive rows, with a killable process."""
    try:
        while True:
            message=connection.recv()
            if message is None:break
            module,function,args,kwargs=message
            try:
                value=getattr(importlib.import_module(module),function)(*args,**kwargs)
                connection.send((True,value))
            except Exception as exc:
                connection.send((False,f'{type(exc).__name__}: {str(exc)[:500]}'))
    except (EOFError,BrokenPipeError):
        pass
    finally:
        connection.close()


def prepare_pdf(path, destination, roi=None):
    import cv2
    import numpy as np
    import pypdfium2 as pdfium
    from app.services.image_io import imwrite
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    with closing(pdfium.PdfDocument(str(path))) as document:
        if len(document) > 100:
            raise ValueError('最多处理 100 页 PDF')
        base_size = None
        for number in range(len(document)):
            page = document[number]
            bitmap = page.render(scale=min(8, 2200 / max(page.get_size())))
            image = cv2.cvtColor(np.asarray(bitmap.to_pil().convert('RGB')), cv2.COLOR_RGB2BGR)
            h, w = image.shape[:2]
            if base_size is None:
                base_size = (w, h)
            if roi:
                x, y, rw, rh = [roi[k] for k in ('x', 'y', 'width', 'height')]
                x, rw = round(x*w/base_size[0]), round(rw*w/base_size[0])
                y, rh = round(y*h/base_size[1]), round(rh*h/base_size[1])
                if min(x, y) < 0 or min(rw, rh) < 1 or x+rw > w or y+rh > h:
                    raise ValueError('PDF 选区超出页面范围')
                image = image[y:y+rh, x:x+rw]
            output = destination / f'pdf-page-{number+1:03d}.png'
            imwrite(output, image)
            paths.append(output)
            bitmap.close()
            page.close()
    return paths


def preview_pdf(path, output, page_number=0):
    import pypdfium2 as pdfium
    with closing(pdfium.PdfDocument(str(path))) as document:
        if not 0 <= page_number < len(document):
            raise ValueError('PDF 页码超出范围')
        page = document[page_number]
        bitmap = page.render(scale=min(8, 2200/max(page.get_size())))
        image = bitmap.to_pil().convert('RGB')
        size = image.size
        image.save(output)
        bitmap.close()
        page.close()
        return dict(width=size[0], height=size[1], pages=len(document))


def prepare_rows(paths, output, layout, video_mode=False, expected_strings=None):
    from app.services.score_images import prepare_images
    from app.services.score_continuity import stitch_rows
    manifest = prepare_images(paths, Path(output), layout, expected_strings=expected_strings)
    if layout == 'standard-tab':
        manifest['continuity_log'] = stitch_rows(Path(output), manifest['rows'],independent_anchors=video_mode)
    return manifest


def video_crops(source, config, roi, output):
    from app.services.frame_extractor import extract_frames
    from app.services.roi_cropper import batch_crop
    from app.models.schemas import ROI
    output = Path(output)
    frames = extract_frames(source, output/'frames', sample_fps=config['sample_fps'],
        start_time=config['start_time'], end_time=config['end_time'], max_frames=config['max_frames'])
    paths=batch_crop(frames, ROI.model_validate(roi), output/'crops', save_debug=False)
    from app.services.revision_store import write
    write(output/'video-sources.json',{
        f'crop_{i:06d}.jpg':dict(frame=path.name,time_estimate=config['start_time']+i/config['sample_fps'],
            uncertainty_seconds=1/config['sample_fps'],roi=roi)
        for i,path in enumerate(frames)})
    return paths


def recover(score, targets, frames, roi, output):
    from app.services.video_score_recovery import index_frame_views, stitch_frame_views, recover_measures
    output = Path(output)
    views = index_frame_views(frames, roi, output/'views')
    return recover_measures(score, targets, stitch_frame_views(views, output/'joined'), output/'evidence')


def review_one(path, row, measure, config, tuning, previous, output):
    from app.services.combined_tab import measure_regions, measure_image
    from app.services.combined_local import number_sequence
    from app.services.image_io import imread, imwrite
    from app.services.local_review import review_measure
    image = imread(Path(path))
    numbers, _ = number_sequence(image, row)
    regions = measure_regions(row)
    if measure.number not in numbers or len(numbers) != len(regions):
        return measure, ['缺少可靠小节位置，未调用模型。']
    crop, _ = measure_image(image, row, regions[numbers.index(measure.number)])
    target = Path(output)
    imwrite(target, crop)
    return review_measure(target, Path(path), measure, config, tuning, previous)
